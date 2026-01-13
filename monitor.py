import os
import datetime
import requests
from googleapiclient.discovery import build
from datetime import timedelta

# Configuration
API_KEY = os.environ.get("YOUTUBE_API_KEY")
PUSH_KEY = os.environ.get("PUSH_KEY")
SEARCH_QUERIES = ["DIY", "Inventions", "Tools", "Gadgets", "Life Hacks"]
MAX_SUBS = 50000        # Max 50k subscribers
MIN_VIEWS = 10000       # Min 10k views
PUBLISHED_AFTER_HOURS = 24  # Look back 24 hours

def get_service():
    if not API_KEY:
        raise ValueError("YOUTUBE_API_KEY not found in environment variables")
    return build('youtube', 'v3', developerKey=API_KEY)

def search_videos(service):
    # Calculate timestamp for 24 hours ago in RFC 3339 format
    published_after = (datetime.datetime.utcnow() - timedelta(hours=PUBLISHED_AFTER_HOURS)).isoformat("T") + "Z"
    
    # We combine queries with OR for a single request to save quota
    # Note: query length is limited, so we pick a few representative tags
    q = "|".join(SEARCH_QUERIES)
    
    print(f"Searching for: {q} published after {published_after}")
    
    # 1 search request cost = 100 units
    request = service.search().list(
        part="snippet",
        q=q,
        type="video",
        order="viewCount",  # Get most viewed first to increase hit rate
        publishedAfter=published_after,
        maxResults=20       # Fetch top 20 candidates
    )
    response = request.execute()
    return response.get("items", [])

def get_video_details(service, video_ids):
    if not video_ids:
        return []
    
    # 1 videos.list request cost = 1 unit
    request = service.videos().list(
        part="statistics,snippet",
        id=",".join(video_ids)
    )
    response = request.execute()
    return response.get("items", [])

def get_channel_details(service, channel_ids):
    if not channel_ids:
        return {}
    
    # Deduplicate IDs
    unique_ids = list(set(channel_ids))
    
    # 1 channels.list request cost = 1 unit
    request = service.channels().list(
        part="statistics",
        id=",".join(unique_ids)
    )
    response = request.execute()
    
    channel_map = {}
    for item in response.get("items", []):
        channel_map[item['id']] = int(item['statistics']['subscriberCount'])
    return channel_map

def send_push(title, url, views, subs, multiplier, thumb_url):
    if not PUSH_KEY:
        print("No PUSH_KEY found, skipping notification.")
        return

    # Check if PUSH_KEY is for PushDeer (starts with PDU) or ServerChan (SCT)
    if PUSH_KEY.startswith("PDU"):
        # PushDeer - Markdown Mode
        base_url = "https://api2.pushdeer.com/message/push"
        
        # Format: Title as text, detailed markdown body as desp
        text = f"🔥 黑马视频: {views}播放 / {subs}订阅"
        desp = f"### [{title}]({url})\n\n![cover]({thumb_url})\n\n- **播放**: {views}\n- **订阅**: {subs}\n- **爆发倍数**: {multiplier:.1f}x\n\n[>>> 点击观看视频]({url})"
        
        try:
            res = requests.get(base_url, params={
                "pushkey": PUSH_KEY, 
                "text": text,
                "desp": desp,
                "type": "markdown"
            })
            print(f"Notification sent for: {title}. Response: {res.status_code} {res.text}")
        except Exception as e:
            print(f"Failed to send notification: {e}")
            
    else:
        # ServerChan (Turbo)
        base_url = f"https://sctapi.ftqq.com/{PUSH_KEY}.send"
        title_short = f"黑马: {multiplier:.1f}倍爆发"
        desp = f"![cover]({thumb_url})\n\n### [{title}]({url})\n\n| 指标 | 数据 |\n| --- | --- |\n| 👁️ 播放 | {views} |\n| 👥 订阅 | {subs} |\n| 🔥 倍数 | {multiplier:.1f}x |\n\n[点击跳转观看]({url})"
        try:
            res = requests.post(base_url, data={"title": title_short, "desp": desp})
            print(f"Notification sent for: {title}. Response: {res.status_code} {res.text}")
        except Exception as e:
            print(f"Failed to send notification: {e}")

def main():
    service = get_service()
    
    # Step 1: Search for videos
    search_results = search_videos(service)
    print(f"Found {len(search_results)} candidates.")
    
    video_ids = [item['id']['videoId'] for item in search_results]
    
    # Step 2: Get video stats (to confirm views)
    video_details = get_video_details(service, video_ids)
    
    # Prepare list of channels to fetch
    channel_ids = [item['snippet']['channelId'] for item in video_details]
    
    # Step 3: Get channel stats (to check subscriber count)
    channel_map = get_channel_details(service, channel_ids)
    
    # Step 4: Filter and Notify
    found_count = 0
    for video in video_details:
        v_stats = video['statistics']
        c_id = video['snippet']['channelId']
        
        views = int(v_stats.get('viewCount', 0))
        subs = channel_map.get(c_id, 999999) # Default to high if not found
        
        # Black Horse Logic
        if subs < MAX_SUBS and views > MIN_VIEWS:
            if subs == 0: subs = 1 # Avoid division by zero
            multiplier = views / subs
            
            title = video['snippet']['title']
            video_id = video['id']
            url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Extract high res thumbnail
            thumb_url = video['snippet']['thumbnails'].get('high', {}).get('url', '')
            if not thumb_url:
                thumb_url = video['snippet']['thumbnails'].get('medium', {}).get('url', '')
            
            print(f"[MATCH] {title} (Views: {views}, Subs: {subs}, Mult: {multiplier:.1f}x)")
            send_push(title, url, views, subs, multiplier, thumb_url)
            found_count += 1
            
    print(f"Done. Found {found_count} black horse videos.")

if __name__ == "__main__":
    main()
