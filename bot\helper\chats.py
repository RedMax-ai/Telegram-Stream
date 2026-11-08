from asyncio import gather, create_task
from bot.helper.database import Database
from bot.telegram import StreamBot
from bot.config import Telegram

db = Database()

async def get_chats():
    AUTH_CHANNEL = await db.get_variable('auth_channel')
    if AUTH_CHANNEL is None or str(AUTH_CHANNEL).strip() == '':
        channels_list = Telegram.AUTH_CHANNEL
    else:
        channels_list = [channel.strip() for channel in str(AUTH_CHANNEL).split(",") if channel.strip()]
    
    if not channels_list:
        return []

    result = []
    for channel_id in channels_list:
        try:
            cid = int(channel_id)
            if hasattr(StreamBot, "is_connected") and StreamBot.is_connected:
                chat = await StreamBot.get_chat(cid)
                result.append({
                    "chat-id": chat.id,
                    "title": chat.title or chat.first_name or f"Channel {cid}",
                    "type": getattr(chat.type, 'name', 'CHANNEL')
                })
            else:
                result.append({
                    "chat-id": cid,
                    "title": f"Channel {cid}",
                    "type": "CHANNEL"
                })
        except Exception:
            result.append({
                "chat-id": int(channel_id) if channel_id.lstrip('-').isdigit() else 0,
                "title": f"Channel {channel_id}",
                "type": "CHANNEL"
            })
    return result


async def posts_chat(channels):
    if not channels:
        return """
        <div class="col-span-full p-8 rounded-2xl glass-panel text-center border border-white/10">
            <div class="size-14 rounded-2xl bg-primary/10 text-primary mx-auto flex items-center justify-center mb-3">
                <span class="material-symbols-outlined text-3xl">podcasts</span>
            </div>
            <h3 class="text-white font-bold text-base mb-1">No Channels Connected</h3>
            <p class="text-slate-400 text-xs max-w-md mx-auto mb-4">Set your channel ID (e.g. -1003904027623) in Storage Settings or config.env, or upload a media file above to stream directly.</p>
            <button type="button" onclick="openStorageConfigModal()" class="px-4 py-2 rounded-xl bg-primary hover:bg-primary-hover text-white text-xs font-semibold shadow-lg shadow-primary/25 transition-all">Configure Channel</button>
        </div>
        """
    phtml = """
    <div class="glass-panel text-center p-6 rounded-2xl hover:bg-white/5 transition-all duration-300 group relative overflow-hidden">
        <a href="/channel/{cid}" class="block">
             <div class="w-24 h-24 mx-auto mb-4 relative rounded-full p-1 bg-gradient-to-br from-primary to-purple-600 shadow-xl shadow-primary/20 group-hover:shadow-primary/40 transition-shadow">
                 <img src="{img}" onerror="this.onerror=null;this.src='https://ui-avatars.com/api/?name={title}&background=6366f1&color=fff';" loading="lazy" class="w-full h-full rounded-full object-cover border-2 border-background-dark/50" alt="{title}">
             </div>
             <h3 class="text-white font-bold text-lg mb-1 truncate px-2">{title}</h3>
             <span class="inline-block px-3 py-1 rounded-full bg-white/5 text-primary text-xs font-semibold uppercase tracking-wider border border-white/5">
                {ctype}
             </span>
        </a>
    </div>
"""
    return ''.join(phtml.format(cid=str(channel["chat-id"]).replace("-100", ""), img=f"/api/thumb/{channel['chat-id']}", title=channel["title"], ctype=channel['type']) for channel in channels)


async def post_playlist(playlists):
    dhtml = """
    <div class="glass-panel text-center p-6 rounded-2xl hover:bg-white/5 transition-all duration-300 group relative">
        <button type="button" onclick="openEditPopupForm(event, '{img}', '{ctype}', '{cid}', '{title}')"
            class="admin-only absolute top-3 right-3 p-1.5 rounded-lg bg-black/50 text-gray-400 hover:text-white hover:bg-primary z-20 transition-colors" 
            title="Edit Folder">
            <span class="material-symbols-outlined text-[16px]">edit</span>
        </button>
        <button type="button" onclick="confirmDeleteFolder(event, '{cid}', '{ctype}')"
            class="admin-only absolute top-3 left-3 p-1.5 rounded-lg bg-black/50 text-red-400 hover:text-white hover:bg-red-600 z-20 transition-colors" 
            title="Delete Folder">
            <span class="material-symbols-outlined text-[16px]">delete</span>
        </button>

        <a href="/playlist?db={cid}" class="block">
             <div class="w-24 h-24 mx-auto mb-4 relative rounded-2xl p-1 bg-gradient-to-br from-yellow-500/80 to-orange-600/80 shadow-lg group-hover:scale-105 transition-transform flex items-center justify-center overflow-hidden">
                 <img src="{img}" onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=200&auto=format&fit=crop&q=60';" loading="lazy" class="w-full h-full rounded-xl object-cover shadow-inner" alt="{title}">
             </div>
             
             <h3 class="text-white font-bold text-lg mb-1 truncate px-2" title="{title}">{title}</h3>
             <span class="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-white/5 text-yellow-500 text-xs font-medium border border-white/5">
                <span class="material-symbols-outlined text-[14px]">folder</span> Folder
             </span>
        </a>
    </div>
    """

    return ''.join(dhtml.format(
        cid=playlist["_id"],
        img=playlist.get("thumbnail") or "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=200&auto=format&fit=crop&q=60",
        title=playlist.get("name", "Untitled Folder"),
        ctype=playlist.get('parent_folder', 'root')
    ) for playlist in playlists)


async def posts_db_file(posts):
    import re
    
    from bot.helper.utils import group_posts_by_series
    
    grouped_posts = group_posts_by_series(posts, title_key='name')
    
    # Sorting (Optional: maintain original order or sort by name)
    # The incoming 'posts' might already be sorted by date. We generally append new series at the end or keep flow.
    # For DB file listing, preserving generic order or sorting by name might be best.
    # Let's simple append for now to not break unexpected pagination orders too much, 
    # but strictly speaking we're mixing non-parts and series.
    # If we want to sort by Name:
    # grouped_posts.sort(key=lambda x: x['name'])
    
    phtml = """
    <div class="glass-panel rounded-xl overflow-hidden hover:shadow-xl hover:shadow-primary/10 transition-all duration-300 group relative">
        <a href="/watch/{chat_id}?id={id}&hash={hash}" class="block relative aspect-video bg-gray-900 overflow-hidden cursor-pointer">
             <img src="{img}" loading="lazy" class="w-full h-full object-cover transition-transform duration-700 group-hover:scale-105" alt="{title}">
             
             <!-- Gradient Overlay -->
             <div class="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-60 group-hover:opacity-40 transition-opacity"></div>
             
             <!-- Centered Play Icon on Hover -->
             <div class="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all duration-300 scale-75 group-hover:scale-100">
                <div class="w-12 h-12 bg-primary/90 rounded-full flex items-center justify-center backdrop-blur-sm shadow-lg shadow-black/50">
                    <span class="material-symbols-outlined text-white text-3xl ml-0.5">play_arrow</span>
                </div>
             </div>
             
             <div class="absolute bottom-2 right-2 bg-black/60 backdrop-blur-md px-2 py-0.5 rounded text-[10px] font-bold text-white tracking-wide">
                {size}
             </div>

            <button type="button"
                onclick="openPostEditPopupForm(event, '{img}', '{type}', '{size}', '{title}', '{cid}', '{ctype}')"
                class="admin-only absolute top-2 right-2 p-1.5 rounded bg-black/50 text-white hover:bg-primary transition-colors z-20" 
                title="Edit File">
                <span class="material-symbols-outlined text-[16px]">edit</span>
            </button>
            <button type="button"
                onclick="confirmDeleteFolder(event, '{cid}', '{ctype}')"
                class="admin-only absolute top-2 left-2 p-1.5 rounded bg-black/50 text-red-400 hover:text-white hover:bg-red-600 transition-colors z-20" 
                title="Delete File">
                <span class="material-symbols-outlined text-[16px]">delete</span>
            </button>
        </a>
        
        <div class="p-3">
            <a href="/watch/{chat_id}?id={id}&hash={hash}" class="block group-hover:text-primary transition-colors duration-200">
                <h3 class="text-white font-medium text-sm line-clamp-2 leading-snug min-h-[2.5rem]" title="{title}">{title}</h3>
            </a>
            
            <div class="flex items-center justify-between mt-3 px-1">
                <span class="px-2 py-0.5 rounded bg-white/5 text-gray-400 text-[10px] uppercase font-bold tracking-wider border border-white/5 {badge_color}">
                    {type_display}
                </span>
            </div>
        </div>
    </div>
"""
    html_output = ''
    for post in grouped_posts:
        if post.get('is_series'):
            type_display = f"SERIES ({post['parts_count']} Parts)"
            badge_color = "text-yellow-400 border-yellow-400/20 bg-yellow-400/10"
        else:
            type_display = post.get('file_type', 'FILE')
            badge_color = ""
            
        html_output += phtml.format(
            cid=post["_id"], 
            chat_id=str(post["chat_id"]).replace("-100", ""), 
            id=post["file_id"], 
            img=post["thumbnail"], 
            title=post["name"], 
            hash=post["hash"], 
            size=post['size'], 
            type=post['file_type'], 
            ctype=post["parent_folder"],
            type_display=type_display,
            badge_color=badge_color
        )
    return html_output
