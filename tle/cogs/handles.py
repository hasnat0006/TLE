import asyncio
import contextlib
import datetime as dt
import html
import io
import logging
import math
import random

import cairo
import discord
from PIL import Image, ImageDraw, ImageFont
from discord.ext import commands

from tle import constants
from tle.util import (
    cache_system2,
    codeforces_api as cf,
    codeforces_common as cf_common,
    db,
    discord_common,
    events,
    paginator,
    table,
    tasks,
)

# Optional Pango support for better text rendering
try:
    import gi
    gi.require_version('Pango', '1.0')
    gi.require_version('PangoCairo', '1.0')
    from gi.repository import Pango, PangoCairo
    PANGO_AVAILABLE = True
except ImportError:
    PANGO_AVAILABLE = False
    # Fallback for cloud environments without gi/Pango
    logging.warning("Pango not available, using fallback text rendering")

def get_gudgitters_image_fallback(rankings):
    """Fallback PIL-only implementation for rankings when Pango is not available"""
    from PIL import Image, ImageDraw, ImageFont
    import os
    
    WIDTH = 900
    HEIGHT = 450
    BORDER_MARGIN = 20
    DISCORD_GRAY_RGB = (54, 62, 63)  # Convert from float
    ROW_COLORS = ((242, 242, 242), (229, 229, 229))  # Convert from float
    
    # Create image
    img = Image.new('RGB', (WIDTH, HEIGHT), color=DISCORD_GRAY_RGB)
    draw = ImageDraw.Draw(img)
    
    # Try to load a font, fall back to default if needed
    try:
        font_path = os.path.join('data', 'assets', 'fonts', 'NotoSansCJK-Regular.ttc')
        if os.path.exists(font_path):
            font = ImageFont.truetype(font_path, 18)
        else:
            font = ImageFont.load_default()
    except:
        font = ImageFont.load_default()
    
    # Draw header
    y = BORDER_MARGIN
    header_height = 30
    draw.rectangle([0, y, WIDTH, y + header_height], fill=ROW_COLORS[0])
    draw.text((BORDER_MARGIN, y + 5), "Rank  Username               Handle                 Rating", 
              fill=(0, 0, 0), font=font)
    y += header_height + 5
    
    # Draw rankings
    row_height = 25
    for i, ranking in enumerate(rankings[:10]):  # Limit to 10 rows
        if i >= 10:
            break
            
        # Alternate row colors
        color_idx = i % 2
        draw.rectangle([0, y, WIDTH, y + row_height], fill=ROW_COLORS[color_idx])
        
        # Get color for rating
        rating = getattr(ranking, 'rating', 0)
        color_rgb = (0, 0, 0)  # Default black
        
        # Format text
        pos = str(getattr(ranking, 'pos', i + 1))
        username = str(getattr(ranking, 'username', 'N/A'))[:15]  # Truncate
        handle = str(getattr(ranking, 'handle', 'N/A'))[:15]      # Truncate
        rating_text = str(rating)
        
        # Draw text columns
        draw.text((BORDER_MARGIN, y + 3), f"{pos:>3}", fill=color_rgb, font=font)
        draw.text((BORDER_MARGIN + 60, y + 3), username, fill=color_rgb, font=font)
        draw.text((BORDER_MARGIN + 320, y + 3), handle, fill=color_rgb, font=font)
        draw.text((BORDER_MARGIN + 580, y + 3), rating_text, fill=color_rgb, font=font)
        
        y += row_height
    
    return img

_HANDLES_PER_PAGE = 15
_NAME_MAX_LEN = 20
_PAGINATE_WAIT_TIME = 5 * 60  # 5 minutes
_PRETTY_HANDLES_PER_PAGE = 10
_TOP_DELTAS_COUNT = 10
_MAX_RATING_CHANGES_PER_EMBED = 15
_UPDATE_HANDLE_STATUS_INTERVAL = 6 * 60 * 60  # 6 hours


class HandleCogError(commands.CommandError):
    pass


def rating_to_color(rating):
    """returns (r, g, b) pixels values corresponding to rating"""
    # TODO: Integrate these colors with the ranks in codeforces_api.py
    BLACK = (10, 10, 10)
    RED = (255, 20, 20)
    BLUE = (0, 0, 200)
    GREEN = (0, 140, 0)
    ORANGE = (250, 140, 30)
    PURPLE = (160, 0, 120)
    CYAN = (0, 165, 170)
    GREY = (70, 70, 70)
    if rating is None or rating == 'N/A':
        return BLACK
    if rating < 1200:
        return GREY
    if rating < 1400:
        return GREEN
    if rating < 1600:
        return CYAN
    if rating < 1900:
        return BLUE
    if rating < 2100:
        return PURPLE
    if rating < 2400:
        return ORANGE
    return RED


FONTS = [
    'Noto Sans',
    'Noto Sans CJK JP',
    'Noto Sans CJK SC',
    'Noto Sans CJK TC',
    'Noto Sans CJK HK',
    'Noto Sans CJK KR',
]


def get_gudgitters_image(rankings):
    """return PIL image for rankings"""
    if not PANGO_AVAILABLE:
        return get_gudgitters_image_fallback(rankings)
    
    SMOKE_WHITE = (250, 250, 250)
    BLACK = (0, 0, 0)

    DISCORD_GRAY = (0.212, 0.244, 0.247)

    ROW_COLORS = ((0.95, 0.95, 0.95), (0.9, 0.9, 0.9))

    WIDTH = 900
    HEIGHT = 450
    BORDER_MARGIN = 20
    COLUMN_MARGIN = 10
    HEADER_SPACING = 1.25
    WIDTH_RANK = 0.08 * WIDTH
    WIDTH_NAME = 0.38 * WIDTH
    LINE_HEIGHT = (HEIGHT - 2 * BORDER_MARGIN) / (10 + HEADER_SPACING)

    # Cairo+Pango setup
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    context = cairo.Context(surface)
    context.set_line_width(1)
    context.set_source_rgb(*DISCORD_GRAY)
    context.rectangle(0, 0, WIDTH, HEIGHT)
    context.fill()
    layout = PangoCairo.create_layout(context)
    layout.set_font_description(
        Pango.font_description_from_string(','.join(FONTS) + ' 20')
    )
    layout.set_ellipsize(Pango.EllipsizeMode.END)

    def draw_bg(y, color_index):
        nxty = y + LINE_HEIGHT

        # Simple
        context.move_to(BORDER_MARGIN, y)
        context.line_to(WIDTH, y)
        context.line_to(WIDTH, nxty)
        context.line_to(0, nxty)
        context.set_source_rgb(*ROW_COLORS[color_index])
        context.fill()

    def draw_row(pos, username, handle, rating, color, y, bold=False):
        context.set_source_rgb(*[x / 255.0 for x in color])

        context.move_to(BORDER_MARGIN, y)

        def draw(text, width=-1):
            text = html.escape(text)
            if bold:
                text = f'<b>{text}</b>'
            layout.set_width((width - COLUMN_MARGIN) * 1000)  # pixel = 1000 pango units
            layout.set_markup(text, -1)
            PangoCairo.show_layout(context, layout)
            context.rel_move_to(width, 0)

        draw(pos, WIDTH_RANK)
        draw(username, WIDTH_NAME)
        draw(handle, WIDTH_NAME)
        draw(rating)

    #

    y = BORDER_MARGIN

    # draw header
    draw_row('#', 'Name', 'Handle', 'Points', SMOKE_WHITE, y, bold=True)
    y += LINE_HEIGHT * HEADER_SPACING

    for i, (pos, name, handle, rating, score) in enumerate(rankings):
        color = rating_to_color(rating)
        draw_bg(y, i % 2)
        draw_row(
            str(pos),
            f'{name} ({rating if rating else "N/A"})',
            handle,
            str(score),
            color,
            y,
        )
        if rating and rating >= 3000:  # nutella
            draw_row('', name[0], handle[0], '', BLACK, y)
        y += LINE_HEIGHT

    image_data = io.BytesIO()
    surface.write_to_png(image_data)
    image_data.seek(0)
    discord_file = discord.File(image_data, filename='gudgitters.png')
    return discord_file


def get_prettyhandles_image(rows, font):
    """return PIL image for rankings"""
    SMOKE_WHITE = (250, 250, 250)
    BLACK = (0, 0, 0)
    img = Image.new('RGB', (900, 450), color=SMOKE_WHITE)
    draw = ImageDraw.Draw(img)

    START_X, START_Y = 20, 20
    Y_INC = 32
    WIDTH_RANK = 64
    WIDTH_NAME = 340

    def draw_row(pos, username, handle, rating, color, y):
        x = START_X
        draw.text((x, y), pos, fill=color, font=font)
        x += WIDTH_RANK
        draw.text((x, y), username, fill=color, font=font)
        x += WIDTH_NAME
        draw.text((x, y), handle, fill=color, font=font)
        x += WIDTH_NAME
        draw.text((x, y), rating, fill=color, font=font)

    y = START_Y
    # draw header
    draw_row('#', 'Username', 'Handle', 'Rating', BLACK, y)
    y += int(Y_INC * 1.5)

    # trim name to fit in the column width
    def _trim(name):
        width = WIDTH_NAME - 10
        while font.getsize(name)[0] > width:
            name = name[:-4] + '...'  # "…" is printed as floating dots
        return name

    for pos, name, handle, rating in rows:
        name = _trim(name)
        handle = _trim(handle)
        color = rating_to_color(rating)
        draw_row(str(pos), name, handle, str(rating) if rating else 'N/A', color, y)
        if rating and rating >= 3000:  # nutella
            nutella_x = START_X + WIDTH_RANK
            draw.text((nutella_x, y), name[0], fill=BLACK, font=font)
            nutella_x += WIDTH_NAME
            draw.text((nutella_x, y), handle[0], fill=BLACK, font=font)
        y += Y_INC

    return img


def _make_profile_embed(member, user, *, mode):
    assert mode in ('set', 'get')
    if mode == 'set':
        desc = (
            f'Handle for {member.mention} successfully set to'
            f' **[{user.handle}]({user.url})**'
        )
    else:
        desc = (
            f'Handle for {member.mention} is currently set to'
            f' **[{user.handle}]({user.url})**'
        )
    if user.rating is None:
        embed = discord.Embed(description=desc)
        embed.add_field(name='Rating', value='Unrated', inline=True)
    else:
        embed = discord.Embed(description=desc, color=user.rank.color_embed)
        embed.add_field(name='Rating', value=user.rating, inline=True)
        embed.add_field(name='Rank', value=user.rank.title, inline=True)
    embed.set_thumbnail(url=f'{user.titlePhoto}')
    return embed


def _make_pages(users, title):
    chunks = paginator.chunkify(users, _HANDLES_PER_PAGE)
    pages = []
    done = 0

    style = table.Style('{:>}  {:<}  {:<}  {:<}')
    for chunk in chunks:
        t = table.Table(style)
        t += table.Header('#', 'Name', 'Handle', 'Rating')
        t += table.Line()
        for i, (member, handle, rating) in enumerate(chunk):
            name = member.display_name
            if len(name) > _NAME_MAX_LEN:
                name = name[: _NAME_MAX_LEN - 1] + '…'
            rank = cf.rating2rank(rating)
            rating_str = 'N/A' if rating is None else str(rating)
            t += table.Data(i + done, name, handle, f'{rating_str} ({rank.title_abbr})')
        table_str = '```\n' + str(t) + '\n```'
        embed = discord_common.cf_color_embed(description=table_str)
        pages.append((title, embed))
        done += len(chunk)
    return pages


class Handles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger(self.__class__.__name__)
        self.font = ImageFont.truetype(
            constants.NOTO_SANS_CJK_BOLD_FONT_PATH, size=26
        )  # font for ;handle pretty
        self.converter = commands.MemberConverter()

    @commands.Cog.listener()
    @discord_common.once
    async def on_ready(self):
        cf_common.event_sys.add_listener(self._on_rating_changes)
        self._set_ex_users_inactive_task.start()

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        cf_common.user_db.set_inactive([(member.guild.id, member.id)])

    @commands.command(brief='update status, mark guild members as active')
    @commands.has_role(constants.TLE_ADMIN)
    async def _updatestatus(self, ctx):
        gid = ctx.guild.id
        active_ids = [m.id for m in ctx.guild.members]
        cf_common.user_db.reset_status(gid)
        rc = sum(
            cf_common.user_db.update_status(gid, chunk)
            for chunk in paginator.chunkify(active_ids, 100)
        )
        await ctx.send(f'{rc} members active with handle')

    @commands.Cog.listener()
    async def on_member_join(self, member):
        rc = cf_common.user_db.update_status(member.guild.id, [member.id])
        if rc == 1:
            handle = cf_common.user_db.get_handle(member.id, member.guild.id)
            await self._update_ranks(member.guild, [(int(member.id), handle)])

    @tasks.task_spec(
        name='SetExUsersInactive',
        waiter=tasks.Waiter.fixed_delay(_UPDATE_HANDLE_STATUS_INTERVAL),
    )
    async def _set_ex_users_inactive_task(self, _):
        # To set users inactive in case the bot was dead when they left.
        to_set_inactive = []
        for guild in self.bot.guilds:
            user_id_handle_pairs = cf_common.user_db.get_handles_for_guild(guild.id)
            to_set_inactive += [
                (guild.id, user_id)
                for user_id, _ in user_id_handle_pairs
                if guild.get_member(user_id) is None
            ]
        cf_common.user_db.set_inactive(to_set_inactive)

    @events.listener_spec(
        name='RatingChangesListener',
        event_cls=events.RatingChangesUpdate,
        with_lock=True,
    )
    async def _on_rating_changes(self, event):
        contest, changes = event.contest, event.rating_changes
        change_by_handle = {change.handle: change for change in changes}

        async def update_for_guild(guild):
            # Check and update achievements first
            achievements = await self._check_and_update_achievements(guild, change_by_handle)
            
            if cf_common.user_db.has_auto_role_update_enabled(guild.id):
                with contextlib.suppress(HandleCogError):
                    await self._update_ranks_all(guild)
            
            channel_id = cf_common.user_db.get_rankup_channel(guild.id)
            channel = guild.get_channel(channel_id)
            if channel is not None:
                # Send achievement congratulations if any
                if achievements:
                    with contextlib.suppress(HandleCogError):
                        achievement_embeds = self._make_achievement_embeds(
                            guild, contest, achievements
                        )
                        for embed in achievement_embeds:
                            await channel.send(embed=embed)

        await asyncio.gather(
            *(update_for_guild(guild) for guild in self.bot.guilds),
            return_exceptions=True,
        )
        self.logger.info(f'All guilds updated for contest {contest.id}.')

    @commands.group(
        brief='Commands that have to do with handles', invoke_without_command=True
    )
    async def handle(self, ctx):
        """Change or collect information about specific handles on Codeforces"""
        await ctx.send_help(ctx.command)

    async def maybe_add_trusted_role(self, member):
        """Add trusted role for eligible users.

        Condition: `member` has been 1900+ for any amount of time before o1 release.
        """
        handle = cf_common.user_db.get_handle(member.id, member.guild.id)
        if not handle:
            self.logger.warning(
                'WARN: handle not found in guild'
                f' {member.guild.name} ({member.guild.id})'
            )
            return
        trusted_role = discord.utils.get(member.guild.roles, name=constants.TLE_TRUSTED)
        if not trusted_role:
            self.logger.warning(
                "WARN: 'Trusted' role not found in guild"
                f' {member.guild.name} ({member.guild.id})'
            )
            return

        if trusted_role not in member.roles:
            # o1 released sept 12 2024
            cutoff_timestamp = dt.datetime(
                2024, 9, 11, tzinfo=dt.timezone.utc
            ).timestamp()
            try:
                rating_changes = await cf.user.rating(handle=handle)
            except cf.NotFoundError:
                # User rating info not found via API, ignore for trusted check
                self.logger.info(
                    'INFO: Rating history not found for'
                    f' handle {handle} during trusted check.'
                )
                return
            except cf.CodeforcesApiError as e:
                # Log API errors appropriately in a real scenario
                self.logger.warning(
                    f'WARN: API Error fetching rating for {handle}'
                    f' during trusted check: {e}'
                )
                return

            if any(
                change.newRating >= 1900
                and change.ratingUpdateTimeSeconds < cutoff_timestamp
                for change in rating_changes
            ):
                try:
                    await member.add_roles(
                        trusted_role, reason='Historical rating >= 1900 before Aug 2024'
                    )
                except discord.Forbidden:
                    self.logger.warning(
                        f'WARN: Missing permissions to add Trusted role to'
                        f' {member.display_name} in {member.guild.name}'
                    )
                except discord.HTTPException as e:
                    self.logger.warning(
                        f'WARN: Failed to add Trusted role to'
                        f' {member.display_name} in {member.guild.name}: {e}'
                    )

    async def update_member_rank_role(self, member, role_to_assign, *, reason):
        """Sets the `member` to only have the rank role of `role_to_assign`.

        All other rank roles on the member, if any, will be removed. If
        `role_to_assign` is None all existing rank roles on the member will be
        removed.
        """
        role_names_to_remove = {rank.title for rank in cf.RATED_RANKS}
        if role_to_assign is not None:
            role_names_to_remove.discard(role_to_assign.name)
            if role_to_assign.name not in ['Newbie', 'Pupil', 'Specialist', 'Expert']:
                role_names_to_remove.add(constants.TLE_PURGATORY)
                await self.maybe_add_trusted_role(member)
        to_remove = [role for role in member.roles if role.name in role_names_to_remove]
        if to_remove:
            await member.remove_roles(*to_remove, reason=reason)
        if role_to_assign is not None and role_to_assign not in member.roles:
            await member.add_roles(role_to_assign, reason=reason)

    @handle.command(brief='Set Codeforces handle of a user', aliases=['link'])
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def set(self, ctx, member: discord.Member, handle: str):
        """Set Codeforces handle of a user."""
        # CF API returns correct handle ignoring case, update to it
        (user,) = await cf.user.info(handles=[handle])
        await self._set(ctx, member, user)
        embed = _make_profile_embed(member, user, mode='set')
        await ctx.send(embed=embed)

    async def _set(self, ctx, member, user):
        handle = user.handle
        try:
            cf_common.user_db.set_handle(member.id, ctx.guild.id, handle)
        except db.UniqueConstraintFailed:
            raise HandleCogError(
                f'When setting handle for {member}: '
                f'The handle `{handle}` is already associated with another user.'
            )
        cf_common.user_db.cache_cf_user(user)
        
        # Sync achievements: initialize with current max rating and highest rank
        # Get the user's rating history to find their actual max rating
        try:
            rating_changes = await cf.user.rating(handle=handle)
            if rating_changes:
                # Find max rating from history
                max_rating_from_history = max(change.newRating for change in rating_changes)
                # Get all ranks achieved
                ranks_achieved = [cf.rating2rank(change.newRating) for change in rating_changes]
                rank_order = list(cf.RATED_RANKS)
                # Find the highest rank (latest in rank_order list)
                highest_rank = max(ranks_achieved, key=lambda r: rank_order.index(r) if r in rank_order else -1)
                highest_rank_title = highest_rank.title
            else:
                # No rating history, use current values
                max_rating_from_history = user.maxRating if user.maxRating else (user.rating if user.rating else 0)
                highest_rank_title = user.rank.title if user.rank != cf.UNRATED_RANK else None
        except (cf.NotFoundError, cf.CodeforcesApiError):
            # Fallback to current user data if API fails
            max_rating_from_history = user.maxRating if user.maxRating else (user.rating if user.rating else 0)
            highest_rank_title = user.rank.title if user.rank != cf.UNRATED_RANK else None
        
        # Initialize or update achievements record
        if max_rating_from_history and highest_rank_title:
            cf_common.user_db.update_user_achievement(
                str(member.id), str(ctx.guild.id), handle,
                max_rating_from_history, highest_rank_title
            )

        # Assign role based on maxRating, not current rating
        max_rating = user.maxRating if user.maxRating else user.rating
        if max_rating is None:
            role_to_assign = None
        else:
            rank_based_on_max = cf.rating2rank(max_rating)
            if rank_based_on_max == cf.UNRATED_RANK:
                role_to_assign = None
            else:
                roles = [role for role in ctx.guild.roles if role.name == rank_based_on_max.title]
                if not roles:
                    raise HandleCogError(
                        f'Role for rank `{rank_based_on_max.title}` not present in the server'
                    )
                role_to_assign = roles[0]
        await self.update_member_rank_role(
            member, role_to_assign, reason='New handle set for user'
        )

    @handle.command(brief='Identify yourself', usage='[handle]')
    @cf_common.user_guard(
        group='handle',
        get_exception=lambda: HandleCogError(
            'Identification is already running for you'
        ),
    )
    async def identify(self, ctx, handle: str):
        """Link a codeforces account to discord account.

        Confirmation is done by submitting a compile error to a random problem.
        """
        if cf_common.user_db.get_handle(ctx.author.id, ctx.guild.id):
            raise HandleCogError(
                f'{ctx.author.mention}, you cannot identify when your handle'
                ' is already set. Ask an Admin or Moderator if you wish to change it'
            )

        if cf_common.user_db.get_user_id(handle, ctx.guild.id):
            raise HandleCogError(
                f'The handle `{handle}` is already associated with another user.'
                ' Ask an Admin or Moderator in case of an inconsistency.'
            )

        if handle in cf_common.HandleIsVjudgeError.HANDLES:
            raise cf_common.HandleIsVjudgeError(handle)

        users = await cf.user.info(handles=[handle])
        invoker = str(ctx.author)
        handle = users[0].handle
        problems = [
            prob
            for prob in cf_common.cache2.problem_cache.problems
            if prob.rating <= 1200
        ]
        problem = random.choice(problems)
        await ctx.send(
            f'`{invoker}`, submit a compile error to <{problem.url}> within 60 seconds'
        )
        await asyncio.sleep(60)

        subs = await cf.user.status(handle=handle, count=5)
        if any(
            sub.problem.name == problem.name and sub.verdict == 'COMPILATION_ERROR'
            for sub in subs
        ):
            (user,) = await cf.user.info(handles=[handle])
            await self._set(ctx, ctx.author, user)
            embed = _make_profile_embed(ctx.author, user, mode='set')
            await ctx.send(embed=embed)
        else:
            await ctx.send(f'Sorry `{invoker}`, can you try again?')

    @handle.command(brief='Get handle by Discord username')
    async def get(self, ctx, member: discord.Member):
        """Show Codeforces handle of a user."""
        handle = cf_common.user_db.get_handle(member.id, ctx.guild.id)
        if not handle:
            raise HandleCogError(f'Handle for {member.mention} not found in database')
        user = cf_common.user_db.fetch_cf_user(handle)
        embed = _make_profile_embed(member, user, mode='get')
        await ctx.send(embed=embed)

    @handle.command(brief='Get Discord username by cf handle')
    async def rget(self, ctx, handle: str):
        """Show Discord username of a cf handle."""
        user_id = cf_common.user_db.get_user_id(handle, ctx.guild.id)
        if not user_id:
            raise HandleCogError(
                f'Discord username for `{handle}` not found in database'
            )
        user = cf_common.user_db.fetch_cf_user(handle)
        member = ctx.guild.get_member(user_id)
        if member is None:
            raise HandleCogError(f'{user_id} not found in the guild')
        embed = _make_profile_embed(member, user, mode='get')
        await ctx.send(embed=embed)

    @handle.command(brief='Unlink handle', aliases=['unlink'])
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def remove(self, ctx, handle: str):
        """Remove Codeforces handle of a user."""
        (handle,) = await cf_common.resolve_handles(ctx, self.converter, [handle])
        user_id = cf_common.user_db.get_user_id(handle, ctx.guild.id)
        if user_id is None:
            raise HandleCogError(f'{handle} not found in database')

        cf_common.user_db.remove_handle(handle, ctx.guild.id)
        member = ctx.guild.get_member(user_id)
        await self.update_member_rank_role(
            member, role_to_assign=None, reason='Handle unlinked'
        )
        embed = discord_common.embed_success(f'Removed {handle} from database')
        await ctx.send(embed=embed)

    @handle.command(brief="Resolve redirect of a user's handle")
    async def unmagic(self, ctx):
        """Updates handle of the calling user if they have changed handles
        (typically new year's magic)"""
        member = ctx.author
        handle = cf_common.user_db.get_handle(member.id, ctx.guild.id)
        await self._unmagic_handles(ctx, [handle], {handle: member})

    @handle.command(brief='Resolve handles needing redirection')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def unmagic_all(self, ctx):
        """Updates handles of all users that have changed handles
        (typically new year's magic)"""
        user_id_and_handles = cf_common.user_db.get_handles_for_guild(ctx.guild.id)

        handles = []
        rev_lookup = {}
        for user_id, handle in user_id_and_handles:
            member = ctx.guild.get_member(user_id)
            handles.append(handle)
            rev_lookup[handle] = member
        await self._unmagic_handles(ctx, handles, rev_lookup)

    @handle.command(brief='Show handle resolution for the given handles')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def unmagic_debug(self, ctx: commands.Context, *args: str) -> None:
        """See what the resolve logic would do."""
        handles = list(args)
        skip_filter = False
        if '+skip_filter' in handles:
            handles.remove('+skip_filter')
            skip_filter = True
        handle_cf_user_mapping = await cf.resolve_redirects(handles, skip_filter)

        lines = ['Resolved handles:']
        for handle, cf_user in handle_cf_user_mapping.items():
            if cf_user:
                lines.append(f'{handle} -> {cf_user.handle}')
            else:
                lines.append(f'{handle} -> None')
        await ctx.send(embed=discord_common.embed_success('\n'.join(lines)))

    async def _unmagic_handles(self, ctx, handles, rev_lookup):
        handle_cf_user_mapping = await cf.resolve_redirects(handles)
        mapping = {
            (rev_lookup[handle], handle): cf_user
            for handle, cf_user in handle_cf_user_mapping.items()
        }
        summary_embed = await self._fix_and_report(ctx, mapping)
        await ctx.send(embed=summary_embed)

    async def _fix_and_report(self, ctx, redirections):
        fixed = []
        failed = []
        for (member, handle), cf_user in redirections.items():
            if not cf_user:
                failed.append(handle)
            else:
                await self._set(ctx, member, cf_user)
                fixed.append((handle, cf_user.handle))

        # Return summary embed
        lines = []
        if not fixed and not failed:
            return discord_common.embed_success('No handles updated')
        if fixed:
            lines.append('**Fixed**')
            lines += (f'{old} -> {new}' for old, new in fixed)
        if failed:
            lines.append('**Failed**')
            lines += failed
        return discord_common.embed_success('\n'.join(lines))

    @commands.command(brief='Show gudgitters', aliases=['gitgudders'])
    async def gudgitters(self, ctx):
        """Show the list of users of gitgud with their scores."""
        res = cf_common.user_db.get_gudgitters()
        res.sort(key=lambda r: r[1], reverse=True)

        rankings = []
        index = 0
        for user_id, score in res:
            member = ctx.guild.get_member(int(user_id))
            if member is None:
                continue
            if score > 0:
                handle = cf_common.user_db.get_handle(user_id, ctx.guild.id)
                user = cf_common.user_db.fetch_cf_user(handle)
                if user is None:
                    continue
                discord_handle = member.display_name
                rating = user.rating
                rankings.append((index, discord_handle, handle, rating, score))
                index += 1
            if index == 10:
                break

        if not rankings:
            raise HandleCogError(
                'No one has completed a gitgud challenge,'
                ' send ;gitgud to request and ;gotgud to mark it as complete'
            )
        discord_file = get_gudgitters_image(rankings)
        await ctx.send(file=discord_file)

    @handle.command(brief='Show all handles')
    async def list(self, ctx, *countries):
        """Shows members of the server who have registered their handles and
        their Codeforces ratings. You can additionally specify a list of countries
        if you wish to display only members from those countries. Country data is
        sourced from codeforces profiles. e.g. ;handle list Croatia Slovenia
        """
        # Fetch fresh data from Codeforces API
        user_id_handle_pairs = cf_common.user_db.get_handles_for_guild(ctx.guild.id)
        if not user_id_handle_pairs:
            raise HandleCogError('No members with registered handles.')
        
        # Get all handles
        handles = [handle for _, handle in user_id_handle_pairs]
        
        # Fetch fresh user data from CF API
        try:
            cf_users = await cf.user.info(handles=handles)
            # Update cache with fresh data
            for user in cf_users:
                cf_common.user_db.cache_cf_user(user)
            # Create a mapping of handle to user
            handle_to_user = {user.handle: user for user in cf_users}
        except Exception as e:
            # Fallback to cached data if API fails
            self.logger.warning(f'Failed to fetch fresh data from CF API: {e}')
            res = cf_common.user_db.get_cf_users_for_guild(ctx.guild.id)
            handle_to_user = {cf_user.handle: cf_user for _, cf_user in res}
        
        countries = [country.title() for country in countries]
        users = []
        for user_id, handle in user_id_handle_pairs:
            member = ctx.guild.get_member(user_id)
            if member is None:
                continue
            cf_user = handle_to_user.get(handle)
            if cf_user is None:
                continue
            if countries and cf_user.country not in countries:
                continue
            users.append((member, cf_user.handle, cf_user.rating))
        
        if not users:
            raise HandleCogError('No members with registered handles.')

        users.sort(
            key=lambda x: (1 if x[2] is None else -x[2], x[1])
        )  # Sorting by (-rating, handle)
        title = 'Handles of server members'
        if countries:
            title += ' from ' + ', '.join(f'`{country}`' for country in countries)
        pages = _make_pages(users, title)
        paginator.paginate(
            self.bot,
            ctx.channel,
            pages,
            wait_time=_PAGINATE_WAIT_TIME,
            set_pagenum_footers=True,
        )

    @handle.command(brief='Show handles, but prettier')
    async def pretty(self, ctx, page_no: int = None):
        """Show members of the server who have registered their handles
        and their Codeforces ratings, in color."""
        # Fetch fresh data from Codeforces API
        user_id_handle_pairs = cf_common.user_db.get_handles_for_guild(ctx.guild.id)
        if not user_id_handle_pairs:
            raise HandleCogError('No members with registered handles.')
        
        # Get all handles
        handles = [handle for _, handle in user_id_handle_pairs]
        
        # Fetch fresh user data from CF API
        try:
            cf_users = await cf.user.info(handles=handles)
            # Update cache with fresh data
            for user in cf_users:
                cf_common.user_db.cache_cf_user(user)
            # Create a mapping of handle to user
            handle_to_user = {user.handle: user for user in cf_users}
        except Exception as e:
            # Fallback to cached data if API fails
            self.logger.warning(f'Failed to fetch fresh data from CF API: {e}')
            res = cf_common.user_db.get_cf_users_for_guild(ctx.guild.id)
            handle_to_user = {cf_user.handle: cf_user for _, cf_user in res}
        
        # Build user list with fresh data
        user_id_cf_user_pairs = []
        for user_id, handle in user_id_handle_pairs:
            cf_user = handle_to_user.get(handle)
            if cf_user:
                user_id_cf_user_pairs.append((user_id, cf_user))
        
        user_id_cf_user_pairs.sort(
            key=lambda p: p[1].rating if p[1].rating is not None else -1, reverse=True
        )
        rows = []
        author_idx = None
        for user_id, cf_user in user_id_cf_user_pairs:
            member = ctx.guild.get_member(user_id)
            if member is None:
                continue
            idx = len(rows)
            if member == ctx.author:
                author_idx = idx
            rows.append((idx, member.display_name, cf_user.handle, cf_user.rating))

        if not rows:
            raise HandleCogError('No members with registered handles.')
        max_page = math.ceil(len(rows) / _PRETTY_HANDLES_PER_PAGE) - 1
        if author_idx is None and page_no is None:
            raise HandleCogError(
                f'Please specify a page number between 0 and {max_page}.'
            )

        msg = None
        if page_no is not None:
            if page_no < 0 or max_page < page_no:
                msg_fmt = 'Page number must be between 0 and {}. Showing page {}.'
                if page_no < 0:
                    msg = msg_fmt.format(max_page, 0)
                    page_no = 0
                else:
                    msg = msg_fmt.format(max_page, max_page)
                    page_no = max_page
            start_idx = page_no * _PRETTY_HANDLES_PER_PAGE
        else:
            msg = f'Showing neighbourhood of user `{ctx.author.display_name}`.'
            num_before = (_PRETTY_HANDLES_PER_PAGE - 1) // 2
            start_idx = max(0, author_idx - num_before)
        rows_to_display = rows[start_idx : start_idx + _PRETTY_HANDLES_PER_PAGE]
        img = get_prettyhandles_image(rows_to_display, self.font)
        buffer = io.BytesIO()
        img.save(buffer, 'png')
        buffer.seek(0)
        await ctx.send(msg, file=discord.File(buffer, 'handles.png'))

    async def _update_ranks_all(self, guild):
        """For each member in the guild, fetches their current ratings and
        updates their role if required.
        """
        res = cf_common.user_db.get_handles_for_guild(guild.id)
        await self._update_ranks(guild, res)

    async def _update_ranks(self, guild, res):
        member_handles = [
            (guild.get_member(user_id), handle) for user_id, handle in res
        ]
        member_handles = [
            (member, handle) for member, handle in member_handles if member is not None
        ]
        if not member_handles:
            raise HandleCogError('Handles not set for any user')
        members, handles = zip(*member_handles, strict=False)
        users = await cf.user.info(handles=handles)
        for user in users:
            cf_common.user_db.cache_cf_user(user)

        # Build required roles based on maxRating, not current rating
        required_roles = set()
        for user in users:
            max_rating = user.maxRating if user.maxRating else user.rating
            if max_rating is not None:
                rank = cf.rating2rank(max_rating)
                if rank != cf.UNRATED_RANK:
                    required_roles.add(rank.title)
        
        rank2role = {
            role.name: role for role in guild.roles if role.name in required_roles
        }
        missing_roles = required_roles - rank2role.keys()
        if missing_roles:
            roles_str = ', '.join(f'`{role}`' for role in missing_roles)
            plural = 's' if len(missing_roles) > 1 else ''
            raise HandleCogError(
                f'Role{plural} for rank{plural} {roles_str} not present in the server'
            )

        for member, user in zip(members, users, strict=False):
            # Assign role based on maxRating, not current rating
            max_rating = user.maxRating if user.maxRating else user.rating
            if max_rating is None:
                role_to_assign = None
            else:
                rank = cf.rating2rank(max_rating)
                role_to_assign = (
                    None if rank == cf.UNRATED_RANK else rank2role[rank.title]
                )
            await self.update_member_rank_role(
                member, role_to_assign, reason='Codeforces rank update'
            )

    @staticmethod
    def _make_rankup_embeds(guild, contest, change_by_handle):
        """Make an embed containing a list of rank changes and top rating
        increases for the members of this guild.
        """
        user_id_handle_pairs = cf_common.user_db.get_handles_for_guild(guild.id)
        member_handle_pairs = [
            (guild.get_member(user_id), handle)
            for user_id, handle in user_id_handle_pairs
        ]

        def ispurg(member):
            # TODO: temporary code, todo properly later
            return any(role.name == constants.TLE_PURGATORY for role in member.roles)

        member_change_pairs = [
            (member, change_by_handle[handle])
            for member, handle in member_handle_pairs
            if member is not None and handle in change_by_handle and not ispurg(member)
        ]
        if not member_change_pairs:
            raise HandleCogError(
                f'Contest `{contest.id} | {contest.name}`'
                ' was not rated for any member of this server.'
            )

        member_change_pairs.sort(key=lambda pair: pair[1].newRating, reverse=True)
        rank_to_role = {role.name: role for role in guild.roles}

        def rating_to_displayable_rank(rating):
            rank = cf.rating2rank(rating).title
            role = rank_to_role.get(rank)
            return role.mention if role else rank

        rank_changes_str = []
        for member, change in member_change_pairs:
            cache = cf_common.cache2.rating_changes_cache
            if (
                change.oldRating == 1500
                and len(cache.get_rating_changes_for_handle(change.handle)) == 1
            ):
                # If this is the user's first rated contest.
                old_role = 'Unrated'
            else:
                old_role = rating_to_displayable_rank(change.oldRating)
            new_role = rating_to_displayable_rank(change.newRating)
            if new_role != old_role:
                rank_change_str = (
                    f'{member.mention}'
                    f' [{change.handle}]({cf.PROFILE_BASE_URL}{change.handle}):'
                    f' {old_role} \N{LONG RIGHTWARDS ARROW} {new_role}'
                )
                rank_changes_str.append(rank_change_str)

        member_change_pairs.sort(
            key=lambda pair: pair[1].newRating - pair[1].oldRating, reverse=True
        )
        top_increases_str = []
        for member, change in member_change_pairs[:_TOP_DELTAS_COUNT]:
            delta = change.newRating - change.oldRating
            if delta <= 0:
                break
            increase_str = (
                f'{member.mention}'
                f' [{change.handle}]({cf.PROFILE_BASE_URL}{change.handle}):'
                f' {change.oldRating} \N{HORIZONTAL BAR} **{delta:+}**'
                f' \N{LONG RIGHTWARDS ARROW} {change.newRating}'
            )
            top_increases_str.append(increase_str)

        rank_changes_str = rank_changes_str or ['No rank changes']

        embed_heading = discord.Embed(
            title=contest.name, url=contest.url, description=''
        )
        embed_heading.set_author(name='Rank updates')
        embeds = [embed_heading]

        for rank_changes_chunk in paginator.chunkify(
            rank_changes_str, _MAX_RATING_CHANGES_PER_EMBED
        ):
            desc = '\n'.join(rank_changes_chunk)
            embed = discord.Embed(description=desc)
            embeds.append(embed)

        top_rating_increases_embed = discord.Embed(
            description='\n'.join(top_increases_str) or 'Nobody got a positive delta :('
        )
        top_rating_increases_embed.set_author(name='Top rating increases')

        embeds.append(top_rating_increases_embed)
        discord_common.set_same_cf_color(embeds)

        return embeds

    @staticmethod
    def _make_achievement_embeds(guild, contest, achievements_by_member):
        """Make embeds for users who achieved new max ratings or new ranks."""
        if not achievements_by_member:
            return []
        
        embeds = []
        
        # Create main achievement heading
        embed_heading = discord.Embed(
            title=contest.name, 
            url=contest.url, 
            description='🎉 Achievements unlocked! 🎉'
        )
        embeds.append(embed_heading)
        
        achievement_messages = []
        
        for member, achievement_info in achievements_by_member:
            handle = achievement_info['handle']
            new_rating = achievement_info['new_rating']
            old_max = achievement_info['old_max']
            new_rank = achievement_info['new_rank']
            old_rank = achievement_info['old_rank']
            is_new_max = achievement_info['is_new_max']
            is_new_rank = achievement_info['is_new_rank']
            
            messages = []
            
            if is_new_max:
                messages.append(
                    f"🌟 **New Max Rating!** {old_max} → **{new_rating}**"
                )
            
            if is_new_rank:
                messages.append(
                    f"🏆 **New Rank Achieved!** {old_rank} → **{new_rank}**"
                )
            
            if messages:
                achievement_str = (
                    f"{member.mention} [{discord.utils.escape_markdown(handle)}]"
                    f"({cf.PROFILE_BASE_URL}{handle})\n" +
                    "\n".join(f"  {msg}" for msg in messages)
                )
                achievement_messages.append(achievement_str)
        
        # Split into multiple embeds if needed
        for chunk in paginator.chunkify(achievement_messages, _MAX_RATING_CHANGES_PER_EMBED):
            desc = '\n\n'.join(chunk)
            embed = discord.Embed(description=desc)
            embeds.append(embed)
        
        discord_common.set_same_cf_color(embeds)
        return embeds

    @staticmethod
    async def _check_and_update_achievements(guild, change_by_handle):
        """Check for new achievements (max rating, new ranks) and update records."""
        user_id_handle_pairs = cf_common.user_db.get_handles_for_guild(guild.id)
        member_handle_pairs = [
            (guild.get_member(user_id), handle)
            for user_id, handle in user_id_handle_pairs
        ]
        
        achievements_by_member = []
        
        for member, handle in member_handle_pairs:
            if member is None or handle not in change_by_handle:
                continue
            
            change = change_by_handle[handle]
            new_rating = change.newRating
            new_rank = cf.rating2rank(new_rating).title
            
            # Get user's previous achievements
            old_max, old_highest_rank = cf_common.user_db.get_user_achievement(
                str(member.id), str(guild.id)
            )
            
            is_new_max = False
            is_new_rank = False
            
            # Check if this is a new max rating
            if old_max is None or new_rating > old_max:
                is_new_max = True
                old_max = old_max or new_rating
            
            # Get rank hierarchy for comparison
            rank_order = [rank.title for rank in cf.RATED_RANKS]
            
            # Check if this is a new rank achievement
            if old_highest_rank is None:
                is_new_rank = True
                old_rank = 'Unrated'
            else:
                try:
                    old_rank_idx = rank_order.index(old_highest_rank)
                    new_rank_idx = rank_order.index(new_rank)
                    if new_rank_idx > old_rank_idx:
                        is_new_rank = True
                    old_rank = old_highest_rank
                except ValueError:
                    # Rank not found in list, skip
                    old_rank = old_highest_rank or 'Unrated'
            
            # If either achievement is new, record it
            if is_new_max or is_new_rank:
                # Update the highest achieved values
                current_max = max(new_rating, old_max) if old_max else new_rating
                
                # Update highest rank if new rank is higher
                if is_new_rank or old_highest_rank is None:
                    current_highest_rank = new_rank
                else:
                    current_highest_rank = old_highest_rank
                
                cf_common.user_db.update_user_achievement(
                    str(member.id), str(guild.id), handle, 
                    current_max, current_highest_rank
                )
                
                # Only announce achievements for Pupil rank and above (rating >= 1200)
                if new_rating >= 1200:
                    achievements_by_member.append((member, {
                        'handle': handle,
                        'new_rating': new_rating,
                        'old_max': old_max,
                        'new_rank': new_rank,
                        'old_rank': old_rank,
                        'is_new_max': is_new_max,
                        'is_new_rank': is_new_rank,
                    }))
        
        return achievements_by_member

    @commands.group(brief='Commands for role updates', invoke_without_command=True)
    async def roleupdate(self, ctx):
        """Group for commands involving role updates."""
        await ctx.send_help(ctx.command)

    @roleupdate.command(brief='Update Codeforces rank roles')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def now(self, ctx):
        """Updates Codeforces rank roles for every member in this server."""
        await self._update_ranks_all(ctx.guild)
        await ctx.send(
            embed=discord_common.embed_success('Roles updated successfully.')
        )

    @roleupdate.command(brief='Enable or disable auto role updates', usage='on|off')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def auto(self, ctx, arg):
        """Auto role update refers to automatic updating of rank roles when rating
        changes are released on Codeforces. 'on'/'off' disables or enables auto role
        updates.
        """
        if arg == 'on':
            rc = cf_common.user_db.enable_auto_role_update(ctx.guild.id)
            if not rc:
                raise HandleCogError('Auto role update is already enabled.')
            await ctx.send(
                embed=discord_common.embed_success('Auto role updates enabled.')
            )
        elif arg == 'off':
            rc = cf_common.user_db.disable_auto_role_update(ctx.guild.id)
            if not rc:
                raise HandleCogError('Auto role update is already disabled.')
            await ctx.send(
                embed=discord_common.embed_success('Auto role updates disabled.')
            )
        else:
            raise ValueError(f"arg must be 'on' or 'off', got '{arg}' instead.")

    @roleupdate.command(
        brief='Publish a rank update for the given contest', usage='here|off|contest_id'
    )
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def publish(self, ctx, arg):
        """This is a feature to publish a summary of rank changes and top rating
        increases in a particular contest for members of this server. 'here' will
        automatically publish the summary to this channel whenever rating changes on
        Codeforces are released. 'off' will disable auto publishing. Specifying a
        contest id will publish the summary immediately.
        """
        if arg == 'here':
            cf_common.user_db.set_rankup_channel(ctx.guild.id, ctx.channel.id)
            await ctx.send(
                embed=discord_common.embed_success(
                    'Auto rank update publishing enabled.'
                )
            )
        elif arg == 'off':
            rc = cf_common.user_db.clear_rankup_channel(ctx.guild.id)
            if not rc:
                raise HandleCogError('Rank update publishing is already disabled.')
            await ctx.send(
                embed=discord_common.embed_success('Rank update publishing disabled.')
            )
        else:
            try:
                contest_id = int(arg)
            except ValueError:
                raise ValueError(
                    f"arg must be 'here', 'off' or a contest ID, got '{arg}' instead."
                )
            await self._publish_now(ctx, contest_id)

    @roleupdate.command(brief='Get or set the rankup channel')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def channel(self, ctx):
        """Shows the currently configured rankup channel. 
        To set it, use `;roleupdate publish here` in the desired channel."""
        channel_id = cf_common.user_db.get_rankup_channel(ctx.guild.id)
        
        if channel_id is None:
            await ctx.send(
                embed=discord_common.embed_neutral(
                    'No rankup channel configured.\n\n'
                    'To set one, use `;roleupdate publish here` in the desired channel.'
                )
            )
            return
        
        channel = ctx.guild.get_channel(channel_id)
        if channel is None:
            await ctx.send(
                embed=discord_common.embed_alert(
                    'The configured rankup channel no longer exists.\n\n'
                    'Use `;roleupdate publish here` to set a new one.'
                )
            )
            return
        
        embed = discord_common.embed_success('Current rankup channel')
        embed.add_field(name='Channel', value=channel.mention)
        embed.add_field(
            name='Info',
            value='This channel will receive:\n'
                  '• Rank change notifications\n'
                  '• Achievement congratulations 🎉\n'
                  '• Top rating increases',
            inline=False
        )
        await ctx.send(embed=embed)

    async def _publish_now(self, ctx, contest_id):
        try:
            contest = cf_common.cache2.contest_cache.get_contest(contest_id)
        except cache_system2.ContestNotFound as e:
            raise HandleCogError(f'Contest with id `{e.contest_id}` not found.')
        if contest.phase != 'FINISHED':
            raise HandleCogError(
                f'Contest `{contest_id} | {contest.name}` has not finished.'
            )
        try:
            changes = await cf.contest.ratingChanges(contest_id=contest_id)
        except cf.RatingChangesUnavailableError:
            changes = None
        if not changes:
            raise HandleCogError(
                'Rating changes are not available for contest'
                f' `{contest_id} | {contest.name}`.'
            )

        change_by_handle = {change.handle: change for change in changes}
        
        # Check for achievements
        achievements = await self._check_and_update_achievements(ctx.guild, change_by_handle)
        
        # Send rank updates
        rankup_embeds = self._make_rankup_embeds(ctx.guild, contest, change_by_handle)
        for rankup_embed in rankup_embeds:
            await ctx.channel.send(embed=rankup_embed)
        
        # Send achievement congratulations if any
        if achievements:
            achievement_embeds = self._make_achievement_embeds(
                ctx.guild, contest, achievements
            )
            for embed in achievement_embeds:
                await ctx.channel.send(embed=embed)

    async def _generic_remind(self, ctx, action, role_name, what):
        roles = [role for role in ctx.guild.roles if role.name == role_name]
        if not roles:
            raise HandleCogError(f'Role `{role_name}` not present in the server')
        role = roles[0]
        if action == 'give':
            if role in ctx.author.roles:
                await ctx.send(
                    embed=discord_common.embed_neutral(
                        f'You are already subscribed to {what} reminders'
                    )
                )
                return
            await ctx.author.add_roles(
                role, reason=f'User subscribed to {what} reminders'
            )
            await ctx.send(
                embed=discord_common.embed_success(
                    f'Successfully subscribed to {what} reminders'
                )
            )
        elif action == 'remove':
            if role not in ctx.author.roles:
                await ctx.send(
                    embed=discord_common.embed_neutral(
                        f'You are not subscribed to {what} reminders'
                    )
                )
                return
            await ctx.author.remove_roles(
                role, reason=f'User unsubscribed from {what} reminders'
            )
            await ctx.send(
                embed=discord_common.embed_success(
                    f'Successfully unsubscribed from {what} reminders'
                )
            )
        else:
            raise HandleCogError(f'Invalid action {action}')

    @commands.command(
        brief='Grants or removes the specified pingable role',
        usage='[give/remove] [vc/duel]',
    )
    async def role(self, ctx, action: str, which: str):
        """e.g. ;role remove duel"""
        if which == 'vc':
            await self._generic_remind(ctx, action, 'Virtual Contestant', 'vc')
        elif which == 'duel':
            await self._generic_remind(ctx, action, 'Duelist', 'duel')
        else:
            raise HandleCogError(f'Invalid role {which}')

    @discord_common.send_error_if(HandleCogError, cf_common.HandleIsVjudgeError)
    async def cog_command_error(self, ctx, error):
        pass

    @handle.command(brief='Give the Trusted role to another user')
    @commands.has_any_role(
        constants.TLE_ADMIN, constants.TLE_MODERATOR, constants.TLE_TRUSTED
    )
    async def refer(self, ctx, target_user: discord.Member):
        """Allows Trusted users to grant the Trusted role to other users.

        The command fails if the target user has the Purgatory role.
        """
        guild = ctx.guild
        trusted_role_name = constants.TLE_TRUSTED
        purgatory_role_name = constants.TLE_PURGATORY

        if target_user == ctx.author:
            raise HandleCogError('You cannot refer yourself.')

        # Find the Purgatory role
        purgatory_role = discord.utils.get(guild.roles, name=purgatory_role_name)
        if purgatory_role is None:
            # This case might indicate a server setup issue, but we proceed as
            # if the user is not in purgatory
            self.logger.warning(
                f"Role '{purgatory_role_name}'"
                f' not found in guild {guild.name} ({guild.id}).'
            )
        elif purgatory_role in target_user.roles:
            await ctx.send(
                embed=discord_common.embed_alert(
                    f'Cannot grant Trusted role to {target_user.mention}.'
                    f' User is currently in Purgatory.'
                )
            )
            return

        # Find the Trusted role
        trusted_role = discord.utils.get(guild.roles, name=trusted_role_name)
        if trusted_role is None:
            raise HandleCogError(
                f"The role '{trusted_role_name}' does not exist in this server."
            )

        # Check if target user already has the role
        if trusted_role in target_user.roles:
            await ctx.send(
                embed=discord_common.embed_neutral(
                    f'{target_user.mention} already has the Trusted role.'
                )
            )
            return

        # Grant the Trusted role
        try:
            await target_user.add_roles(
                trusted_role, reason=f'Referred by {ctx.author.name} ({ctx.author.id})'
            )
            await ctx.send(
                f'Trusted role granted to {target_user.mention}'
                f' by {ctx.author.mention}.'
            )
        except discord.Forbidden:
            raise HandleCogError(
                f"No permissions to assign the '{trusted_role_name}' role."
            )
        except discord.HTTPException as e:
            raise HandleCogError(
                f'Failed to assign the role due to an unexpected error: {e}'
            )

    @handle.command(brief='Grant Trusted role to old members without Purgatory role.')
    @commands.has_role(constants.TLE_ADMIN)
    async def grandfather(self, ctx):
        """Grants the Trusted role to all members who joined before April 21, 2025,
        and do not currently have the Purgatory role. April 20 was o3's first contest.
        """
        guild = ctx.guild
        trusted_role_name = constants.TLE_TRUSTED
        purgatory_role_name = constants.TLE_PURGATORY

        trusted_role = discord.utils.get(guild.roles, name=trusted_role_name)
        if trusted_role is None:
            raise HandleCogError(
                f"The role '{trusted_role_name}' does not exist in this server."
            )

        purgatory_role = discord.utils.get(guild.roles, name=purgatory_role_name)
        # If Purgatory role doesn't exist, we assume no one has it.
        if purgatory_role is None:
            self.logger.warning(
                f"Role '{purgatory_role_name}'"
                f' not found in guild {guild.name} ({guild.id}).'
                f' Proceeding without Purgatory check.'
            )

        # The date when this code was added.
        # April 20 was o3's first contest.
        cutoff_date = dt.datetime(2025, 4, 21, 0, 0, 0, tzinfo=dt.timezone.utc)

        added_count = 0
        skipped_purgatory = 0
        skipped_already_trusted = 0
        skipped_join_date = 0
        processed_count = 0
        http_failure_count = 0

        status_message = await ctx.send(
            'Processing members for grandfathering Trusted...'
        )

        # Create a list to avoid issues if members leave/join during processing
        members_to_process = list(guild.members)

        for i, member in enumerate(members_to_process):
            processed_count += 1
            if i % 100 == 0 and i > 0:
                await status_message.edit(
                    content=f'Processing members... ({i}/{len(members_to_process)})'
                )

            if purgatory_role is not None and purgatory_role in member.roles:
                # User has purgatory role so is not eligible, skip
                skipped_purgatory += 1
                continue

            if member.joined_at is None:
                # Cannot determine join date, skip
                skipped_join_date += 1
                continue

            # Make member.joined_at timezone-aware
            # (assuming it's UTC, which discord.py uses)
            member_joined_at_aware = member.joined_at.replace(tzinfo=dt.timezone.utc)

            if member_joined_at_aware >= cutoff_date:
                # User joined too late to be eligible, skip
                skipped_join_date += 1
                continue

            if trusted_role in member.roles:
                # User already trusted, skip
                skipped_already_trusted += 1
                continue

            # Eligible for Trusted role, try to grant it
            try:
                await member.add_roles(
                    trusted_role,
                    reason='Grandfather clause: Joined before 2025-04-21 and not in Purgatory',  # noqa: E501
                )
                added_count += 1
                # Short delay to avoid hitting rate limits on large servers
                await asyncio.sleep(0.1)
            except discord.Forbidden:
                await ctx.send(
                    embed=discord_common.embed_alert(
                        f"Missing permissions to assign the '{trusted_role_name}'"
                        f' role to {member.mention}. Stopping.'
                    )
                )
                return  # Stop processing if permissions are missing
            except discord.HTTPException as e:
                self.logger.warning(
                    f'Failed to assign {trusted_role_name} role to'
                    f' {member.display_name} ({member.id}): {e}'
                )
                http_failure_count += 1

        summary_message = (
            f'Grandfathering complete.\n'
            f'- Processed: {processed_count} members\n'
            f'- Granted Trusted: {added_count} members\n'
            f'- Skipped (Joined after cutoff): {skipped_join_date}\n'
            f'- Skipped (Already Trusted): {skipped_already_trusted}\n'
            f'- HTTP failure granting role: {http_failure_count}\n'
        )
        if purgatory_role:
            summary_message += f'- Skipped (Has Purgatory): {skipped_purgatory}\n'

        await status_message.edit(content=summary_message)

    @commands.command(brief='Sync achievements for all users')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def sync_achievements(self, ctx, member: discord.Member = None):
        """Sync contest rank and rating achievements for users.
        
        This command will fetch rating history from Codeforces and update 
        the achievement records (max rating and highest rank) for users.
        
        Usage:
        - ;sync_achievements - Sync all users in the server
        - ;sync_achievements @user - Sync a specific user
        """
        status_msg = await ctx.send('Starting achievement sync...')
        
        if member:
            # Sync single user
            user_id_handle_pairs = [(member.id, cf_common.user_db.get_handle(member.id, ctx.guild.id))]
            if not user_id_handle_pairs[0][1]:
                await status_msg.edit(content=f'{member.mention} has no handle registered.')
                return
        else:
            # Sync all users in guild
            user_id_handle_pairs = cf_common.user_db.get_handles_for_guild(ctx.guild.id)
        
        if not user_id_handle_pairs:
            await status_msg.edit(content='No users with handles found.')
            return
        
        synced = 0
        failed = 0
        skipped = 0
        roles_updated = 0
        
        for i, (user_id, handle) in enumerate(user_id_handle_pairs):
            if i % 10 == 0:
                await status_msg.edit(content=f'Syncing... {i}/{len(user_id_handle_pairs)}')
            
            try:
                # Fetch current user info first to update cache and roles
                users = await cf.user.info(handles=[handle])
                user = users[0]
                
                # Cache the current user data
                cf_common.user_db.cache_cf_user(user)
                
                # Get rating history
                rating_changes = await cf.user.rating(handle=handle)
                
                if rating_changes:
                    # Find max rating from history
                    max_rating = max(change.newRating for change in rating_changes)
                    # Get all ranks achieved
                    ranks_achieved = [cf.rating2rank(change.newRating) for change in rating_changes]
                    rank_order = list(cf.RATED_RANKS)
                    # Find the highest rank
                    highest_rank = max(
                        ranks_achieved, 
                        key=lambda r: rank_order.index(r) if r in rank_order else -1
                    )
                    
                    # Update achievements
                    cf_common.user_db.update_user_achievement(
                        str(user_id), str(ctx.guild.id), handle,
                        max_rating, highest_rank.title
                    )
                    synced += 1
                else:
                    # User has no rating history, use current data
                    if user.maxRating and user.maxRating > 0:
                        max_rating = user.maxRating
                        rank = cf.rating2rank(max_rating)
                        if rank != cf.UNRATED_RANK:
                            cf_common.user_db.update_user_achievement(
                                str(user_id), str(ctx.guild.id), handle,
                                max_rating, rank.title
                            )
                            synced += 1
                        else:
                            skipped += 1
                    else:
                        skipped += 1
                
                # Update member's role based on maxRating
                guild_member = ctx.guild.get_member(user_id)
                if guild_member:
                    max_rating = user.maxRating if user.maxRating else user.rating
                    if max_rating is None:
                        role_to_assign = None
                    else:
                        rank = cf.rating2rank(max_rating)
                        if rank == cf.UNRATED_RANK:
                            role_to_assign = None
                        else:
                            roles = [role for role in ctx.guild.roles if role.name == rank.title]
                            if roles:
                                role_to_assign = roles[0]
                            else:
                                role_to_assign = None
                    
                    if role_to_assign is not None or any(
                        role.name in [r.title for r in cf.RATED_RANKS] 
                        for role in guild_member.roles
                    ):
                        await self.update_member_rank_role(
                            guild_member, role_to_assign, reason='Achievement sync'
                        )
                        roles_updated += 1
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.1)
                
            except (cf.NotFoundError, cf.CodeforcesApiError) as e:
                self.logger.warning(f'Failed to sync achievements for {handle}: {e}')
                failed += 1
        
        summary = (
            f'Achievement sync complete!\n'
            f'✅ Synced: {synced}\n'
            f'🎭 Roles updated: {roles_updated}\n'
            f'⏭️ Skipped (unrated): {skipped}\n'
            f'❌ Failed: {failed}'
        )
        await status_msg.edit(content=summary)

    @commands.command(brief='Check achievement status for a user')
    @commands.has_any_role(constants.TLE_ADMIN, constants.TLE_MODERATOR)
    async def check_achievements(self, ctx, member: discord.Member):
        """Check the current achievement records for a user."""
        handle = cf_common.user_db.get_handle(member.id, ctx.guild.id)
        
        if not handle:
            await ctx.send(embed=discord_common.embed_alert(
                f'{member.mention} has no handle registered.'
            ))
            return
        
        # Get stored achievements
        max_rating, highest_rank = cf_common.user_db.get_user_achievement(
            str(member.id), str(ctx.guild.id)
        )
        
        # Get current rating from CF
        try:
            user = await cf.user.info(handles=[handle])
            current_rating = user[0].rating or 0
            current_max = user[0].maxRating or 0
            current_rank = cf.rating2rank(current_rating).title
        except Exception as e:
            current_rating = "Error fetching"
            current_max = "Error fetching"
            current_rank = "Error fetching"
        
        embed = discord_common.cf_color_embed(
            title=f'Achievement Status for {member.display_name}'
        )
        embed.add_field(
            name='Handle',
            value=f'[{handle}]({cf.PROFILE_BASE_URL}{handle})',
            inline=False
        )
        embed.add_field(
            name='Current CF Stats',
            value=f'Rating: **{current_rating}**\n'
                  f'Max Rating: **{current_max}**\n'
                  f'Rank: **{current_rank}**',
            inline=True
        )
        embed.add_field(
            name='Stored Achievements',
            value=f'Max Rating: **{max_rating or "Not set"}**\n'
                  f'Highest Rank: **{highest_rank or "Not set"}**',
            inline=True
        )
        
        if max_rating is None:
            embed.add_field(
                name='ℹ️ Note',
                value='No achievements recorded yet. They will be tracked after the next rated contest.',
                inline=False
            )
        
        await ctx.send(embed=embed)

    @commands.command(brief='Test achievement detection (Admin only)')
    @commands.has_role(constants.TLE_ADMIN)
    async def test_achievements(self, ctx, contest_id: int):
        """Test the achievement congratulation system with a past contest.
        This will check achievements but not update the database."""
        try:
            contest = cf_common.cache2.contest_cache.get_contest(contest_id)
        except cache_system2.ContestNotFound:
            raise HandleCogError(f'Contest with ID `{contest_id}` not found.')
        
        try:
            changes = await cf.contest.ratingChanges(contest_id=contest_id)
        except cf.RatingChangesUnavailableError:
            raise HandleCogError(f'Rating changes not available for contest `{contest.name}`.')
        
        if not changes:
            raise HandleCogError(f'No rating changes found for contest `{contest.name}`.')
        
        change_by_handle = {change.handle: change for change in changes}
        
        # Check achievements without updating database
        achievements = await self._check_and_update_achievements(ctx.guild, change_by_handle)
        
        if not achievements:
            await ctx.send(embed=discord_common.embed_neutral(
                'No new achievements detected for server members in this contest.'
            ))
            return
        
        # Show achievement embeds
        achievement_embeds = self._make_achievement_embeds(ctx.guild, contest, achievements)
        for embed in achievement_embeds:
            await ctx.channel.send(embed=embed)
        
        await ctx.send(embed=discord_common.embed_success(
            f'Found {len(achievements)} achievement(s)! '
            'Note: Database has been updated with these achievements.'
        ))


def setup(bot):
    bot.add_cog(Handles(bot))
