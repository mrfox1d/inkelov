import string
import random
from datetime import datetime, timedelta

import disnake
from disnake.ext import commands
from db.interaction import Database

db = Database()

CLR_OK   = 0x2EFF7A
CLR_FAIL = 0xFF2E2E
CLR_INFO = 0x00D9FF


def money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " 🪙"


def generate_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


class Promocodes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ──────────────────────── АКТИВАЦИЯ ────────────────────────

    async def _do_redeem(self, ctx_or_inter, code: str, is_slash: bool):
        author = ctx_or_inter.author
        code = code.strip().upper()

        promo = await db.get_promocode(code)

        if not promo or not promo["is_active"]:
            return await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                title="❌ Промокод не найден",
                description="Такого промокода не существует или он деактивирован.",
                color=CLR_FAIL,
            ), ephemeral=True)

        if promo["expires_at"]:
            expires = datetime.fromisoformat(promo["expires_at"])
            if datetime.utcnow() > expires:
                return await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                    title="⌛ Промокод истёк",
                    description=f"Срок действия закончился {disnake.utils.format_dt(expires, style='f')}.",
                    color=CLR_FAIL,
                ), ephemeral=True)

        if promo["max_uses"] != -1 and promo["uses_count"] >= promo["max_uses"]:
            return await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                title="❌ Лимит активаций исчерпан",
                description="Все активации этого промокода уже использованы.",
                color=CLR_FAIL,
            ), ephemeral=True)

        already_used = await db.has_redeemed_promocode(code, author.id)
        if already_used:
            return await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                title="❌ Уже активирован",
                description="Ты уже использовал этот промокод.",
                color=CLR_FAIL,
            ), ephemeral=True)

        # выдача награды
        if promo["reward_type"] == "balance":
            new_balance = await db.add_balance(author.id, promo["reward_amount"], reason=f"Промокод {code}")
            reward_text = f"💰 **{money(promo['reward_amount'])}** зачислено на баланс.\nНовый баланс: **{money(new_balance)}**"

        elif promo["reward_type"] == "item":
            item = await db.get_item(promo["reward_item_id"])
            if not item:
                return await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                    title="❌ Ошибка",
                    description="Товар, привязанный к этому промокоду, больше не существует. Сообщи администрации.",
                    color=CLR_FAIL,
                ), ephemeral=True)

            # выдаём товар напрямую в инвентарь, без списания баланса и без учёта стока
            await db._grant_item_free(author.id, promo["reward_item_id"])

            role_text = ""
            if item["role_id"] and hasattr(ctx_or_inter, "guild") and ctx_or_inter.guild:
                role = ctx_or_inter.guild.get_role(item["role_id"])
                if role:
                    try:
                        await author.add_roles(role, reason=f"Промокод {code}")
                        role_text = f"\n🎭 Выдана роль: {role.mention}"
                    except disnake.Forbidden:
                        pass

            reward_text = f"🎁 Получен товар: **{item['name']}**{role_text}"

        else:
            return await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                title="❌ Ошибка",
                description="Неизвестный тип награды промокода.",
                color=CLR_FAIL,
            ), ephemeral=True)

        await db.redeem_promocode(code, author.id)

        await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
            title="✅ Промокод активирован!",
            description=f"Код `{code}` успешно применён.\n\n{reward_text}",
            color=CLR_OK,
        ), ephemeral=True)

    async def _reply(self, ctx_or_inter, is_slash: bool, embed: disnake.Embed, ephemeral: bool = False):
        if is_slash:
            if ctx_or_inter.response.is_done():
                await ctx_or_inter.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await ctx_or_inter.response.send_message(embed=embed, ephemeral=ephemeral)
        else:
            await ctx_or_inter.send(embed=embed)

    @commands.command(name="promo", aliases=["redeem", "activate"])
    async def txt_promo(self, ctx: commands.Context, code: str):
        """Активировать промокод"""
        await self._do_redeem(ctx, code, is_slash=False)

    @commands.slash_command(name="promo", description="🎟️ Активировать промокод")
    async def slash_promo(self, inter: disnake.AppCmdInter, code: str = commands.Param(description="Промокод")):
        await self._do_redeem(inter, code, is_slash=True)

    # ──────────────────────── АДМИН: СОЗДАНИЕ ────────────────────────

    @commands.command(name="promocreate")
    @commands.has_permissions(administrator=True)
    async def txt_promocreate(
        self, ctx: commands.Context, amount: int, max_uses: int = -1, expires_hours: int = 0, code: str = None
    ):
        """Создать промокод на баланс: !promocreate 500 [макс_использований] [часов_действия] [код]"""
        await self._create_balance_promo(ctx, amount, max_uses, expires_hours, code)

    async def _create_balance_promo(self, ctx_or_inter, amount, max_uses, expires_hours, code):
        is_slash = isinstance(ctx_or_inter, disnake.Interaction)
        author = ctx_or_inter.author

        final_code = (code or generate_code()).strip().upper()
        expires_at = (datetime.utcnow() + timedelta(hours=expires_hours)).isoformat() if expires_hours > 0 else None

        created = await db.create_promocode(
            code=final_code,
            reward_type="balance",
            created_by=author.id,
            reward_amount=amount,
            max_uses=max_uses,
            expires_at=expires_at,
        )

        if not created:
            return await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                title="❌ Код уже существует",
                description=f"Промокод `{final_code}` уже создан. Укажи другой код.",
                color=CLR_FAIL,
            ), ephemeral=True)

        fields_text = (
            f"**Код:** `{final_code}`\n"
            f"**Награда:** {money(amount)}\n"
            f"**Лимит:** {'безлимит' if max_uses == -1 else max_uses}\n"
            f"**Срок:** {'бессрочный' if not expires_at else disnake.utils.format_dt(datetime.fromisoformat(expires_at), style='f')}"
        )

        await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
            title="✅ Промокод создан",
            description=fields_text,
            color=CLR_OK,
        ))

    # ──────────────────────── АДМИН: СОЗДАНИЕ (ТОВАР) ────────────────────────

    @commands.command(name="promocreateitem")
    @commands.has_permissions(administrator=True)
    async def txt_promocreateitem(
        self, ctx: commands.Context, item_id: int, max_uses: int = -1, expires_hours: int = 0, code: str = None
    ):
        """Создать промокод на товар: !promocreateitem <item_id> [макс_использований] [часов_действия] [код]"""
        await self._create_item_promo(ctx, item_id, max_uses, expires_hours, code)

    async def _create_item_promo(self, ctx_or_inter, item_id, max_uses, expires_hours, code):
        is_slash = isinstance(ctx_or_inter, disnake.Interaction)
        author = ctx_or_inter.author

        item = await db.get_item(item_id)
        if not item:
            return await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                title="❌ Товар не найден",
                description=f"Товара с ID `{item_id}` не существует.",
                color=CLR_FAIL,
            ), ephemeral=True)

        final_code = (code or generate_code()).strip().upper()
        expires_at = (datetime.utcnow() + timedelta(hours=expires_hours)).isoformat() if expires_hours > 0 else None

        created = await db.create_promocode(
            code=final_code,
            reward_type="item",
            created_by=author.id,
            reward_item_id=item_id,
            max_uses=max_uses,
            expires_at=expires_at,
        )

        if not created:
            return await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                title="❌ Код уже существует",
                description=f"Промокод `{final_code}` уже создан. Укажи другой код.",
                color=CLR_FAIL,
            ), ephemeral=True)

        fields_text = (
            f"**Код:** `{final_code}`\n"
            f"**Награда:** 🎁 {item['name']}\n"
            f"**Лимит:** {'безлимит' if max_uses == -1 else max_uses}\n"
            f"**Срок:** {'бессрочный' if not expires_at else disnake.utils.format_dt(datetime.fromisoformat(expires_at), style='f')}"
        )

        await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
            title="✅ Промокод создан",
            description=fields_text,
            color=CLR_OK,
        ))

    # ──────────────────────── АДМИН: УПРАВЛЕНИЕ ────────────────────────

    @commands.command(name="promolist")
    @commands.has_permissions(administrator=True)
    async def txt_promolist(self, ctx: commands.Context):
        """Показать список активных промокодов"""
        await self._do_promolist(ctx, is_slash=False)

    async def _do_promolist(self, ctx_or_inter, is_slash: bool):
        promos = await db.get_all_promocodes(only_active=True)

        if not promos:
            return await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                title="🎟️ Промокоды", description="Активных промокодов нет.", color=CLR_INFO,
            ))

        lines = []
        for p in promos:
            uses = f"{p['uses_count']}/{'∞' if p['max_uses'] == -1 else p['max_uses']}"
            reward = money(p["reward_amount"]) if p["reward_type"] == "balance" else f"товар #{p['reward_item_id']}"
            lines.append(f"`{p['code']}` — {reward} — использований: {uses}")

        await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
            title="🎟️ Активные промокоды",
            description="\n".join(lines),
            color=CLR_INFO,
        ))

    @commands.command(name="promodelete", aliases=["promodel"])
    @commands.has_permissions(administrator=True)
    async def txt_promodelete(self, ctx: commands.Context, code: str):
        """Деактивировать промокод"""
        await self._do_promodelete(ctx, code, is_slash=False)

    async def _do_promodelete(self, ctx_or_inter, code: str, is_slash: bool):
        code = code.strip().upper()
        deleted = await db.deactivate_promocode(code)
        if deleted:
            await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                title="✅ Промокод деактивирован", description=f"`{code}` больше не активируется.", color=CLR_OK,
            ))
        else:
            await self._reply(ctx_or_inter, is_slash, embed=disnake.Embed(
                title="❌ Не найден", description=f"Промокод `{code}` не существует.", color=CLR_FAIL,
            ))

    @txt_promocreate.error
    @txt_promocreateitem.error
    @txt_promolist.error
    @txt_promodelete.error
    async def promo_admin_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=disnake.Embed(title="⛔ Нет прав", description="Только для администраторов.", color=CLR_FAIL))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка аргументов", description=f"Не указан обязательный аргумент: `{error.param.name}`", color=CLR_FAIL))
        else:
            await ctx.send(embed=disnake.Embed(title="❌ Ошибка", description=f"```{error}```", color=CLR_FAIL))


def setup(bot: commands.Bot):
    bot.add_cog(Promocodes(bot))