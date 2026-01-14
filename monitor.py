import os
import datetime
import requests
import shutil
import time
from datetime import timedelta
from googleapiclient.discovery import build

# Third-party libraries
import yt_dlp
from moviepy.editor import VideoFileClip, vfx
from aligo import Aligo

# Configuration
API_KEY = os.environ.get("YOUTUBE_API_KEY")
PUSH_KEY = os.environ.get("PUSH_KEY")
ALIYUN_REFRESH_TOKEN = os.environ.get("ALIYUN_REFRESH_TOKEN")

SEARCH_QUERIES = ["DIY", "Inventions", "Tools", "Gadgets", "Life Hacks"]
MAX_SUBS = 50000         # Max 50k subscribers
MIN_VIEWS = 10000        # Min 10k views
MAX_DURATION_SEC = 300   # Max 5 minutes (to avoid timeout)
PUBLISHED_AFTER_HOURS = 24

DOWNLOAD_DIR = "downloads"
OUTPUT_DIR = "output"
ALIYUN_FOLDER_NAME = "YouTube_Monitor"

# --- Helper Functions ---

def get_service():
    if not API_KEY:
        raise ValueError("YOUTUBE_API_KEY not found")
    return build('youtube', 'v3', developerKey=API_KEY)

def cleanup_dirs():
    """Create or clean workspace directories"""
    for d in [DOWNLOAD_DIR, OUTPUT_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d)

def parse_duration(duration_iso):
    """Parse ISO 8601 duration to seconds (e.g., PT1H2M10S)"""
    import isodate
    try:
        dur = isodate.parse_duration(duration_iso)
        return int(dur.total_seconds())
    except:
        return 99999 # Fail safe to skip

# --- Core Logic ---

def search_videos(service):
    published_after = (datetime.datetime.utcnow() - timedelta(hours=PUBLISHED_AFTER_HOURS)).isoformat("T") + "Z"
    q = "|".join(SEARCH_QUERIES)
    print(f"Searching: {q} after {published_after}")
    
    request = service.search().list(
        part="snippet", q=q, type="video", order="viewCount",
        publishedAfter=published_after, maxResults=20
    )
    return request.execute().get("items", [])

def get_video_details(service, video_ids):
    if not video_ids: return []
    request = service.videos().list(
        part="statistics,snippet,contentDetails", # added contentDetails for duration
        id=",".join(video_ids)
    )
    return request.execute().get("items", [])

def get_channel_details(service, channel_ids):
    if not channel_ids: return {}
    unique_ids = list(set(channel_ids))
    request = service.channels().list(
        part="statistics", id=",".join(unique_ids)
    )
    items = request.execute().get("items", [])
    return {item['id']: int(item['statistics']['subscriberCount']) for item in items}

# --- Processing Logic ---

def download_video(url, video_id):
    """Download video using yt-dlp"""
    print(f"Downloading {url}...")
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{DOWNLOAD_DIR}/{video_id}.%(ext)s',
        'quiet': True,
        'no_warnings': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Find the downloaded file
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(video_id):
                return os.path.join(DOWNLOAD_DIR, f)
    except Exception as e:
        print(f"Download failed: {e}")
    return None

def process_video(input_path, video_id):
    """
    Process video:
    1. Horizontal Mirror (vfx.mirror_x)
    2. Increase Contrast 10% (vfx.colorx 1.1)
    3. Increase Brightness 5% (vfx.lum_contrast)
    """
    print(f"Processing {input_path}...")
    output_path = os.path.join(OUTPUT_DIR, f"processed_{video_id}.mp4")
    
    try:
        clip = VideoFileClip(input_path)
        
        # Apply effects
        # 1. Mirror
        clip = clip.fx(vfx.mirror_x)
        # 2. Contrast +10% (Color multiplier)
        clip = clip.fx(vfx.colorx, 1.1)
        # 3. Brightness/Contrast (lum=brightness, contrast=contrast)
        # Using lum_contrast: lum 0.05 adds 5% brightness
        clip = clip.fx(vfx.lum_contrast, lum=0.05, contrast=0)
        
        # Limit processing to first 5 mins if it somehow got past filter
        if clip.duration > 300:
            clip = clip.subclip(0, 300)
            
        clip.write_videofile(
            output_path, 
            codec='libx264', 
            audio_codec='aac', 
            temp_audiofile='temp-audio.m4a', 
            remove_temp=True,
            logger=None # Quiet
        )
        clip.close()
        return output_path
    except Exception as e:
        print(f"Processing failed: {e}")
        return None

def upload_to_aliyun(file_path):
    """Upload to Aliyun Drive using aligo"""
    if not ALIYUN_REFRESH_TOKEN:
        print("Skipping upload: No ALIYUN_REFRESH_TOKEN")
        return None

    print(f"Uploading {file_path} to Aliyun Drive...")
    try:
        ali = Aligo(refresh_token=ALIYUN_REFRESH_TOKEN)
        
        # Get or Create Folder
        folder = ali.get_folder_by_path(ALIYUN_FOLDER_NAME)
        if not folder:
            ali.create_folder(ALIYUN_FOLDER_NAME)
            folder = ali.get_folder_by_path(ALIYUN_FOLDER_NAME)
            
        # Upload
        remote_file = ali.upload_file(file_path, folder.file_id)
        if remote_file:
            print("Upload success!")
            return remote_file.file_id # Or any identifier
        return None
    except Exception as e:
        print(f"Upload failed: {e}")
        return None

# --- Notification Logic ---

def send_push(title, url, views, subs, multiplier, thumb_url, uploaded_status):
    if not PUSH_KEY: return

    upload_msg = "✅ 阿里云盘已上传" if uploaded_status else "⚠️ 暂未上传 (无Token或失败)"
    
    # Common Body
    body_text = f"🔥播放: {views} | 👥订阅: {subs}\n🚀倍数: {multiplier:.1f}x\n📂状态: {upload_msg}"
    
    if PUSH_KEY.startswith("PDU"):
        # PushDeer
        base_url = "https://api2.pushdeer.com/message/push"
        text = f"Found Black Horse: {title}"
        desp = f"### [{title}]({url})\n\n![cover]({thumb_url})\n\n- **播放**: {views}\n- **订阅**: {subs}\n- **倍数**: {multiplier:.1f}x\n- **云盘**: {upload_msg}\n\n[>>> 前往YouTube观看]({url})"
        requests.get(base_url, params={"pushkey": PUSH_KEY, "text": text, "desp": desp, "type": "markdown"})
        
    elif PUSH_KEY.startswith("SCT"):
        # ServerChan
        base_url = f"https://sctapi.ftqq.com/{PUSH_KEY}.send"
        title_short = f"黑马: {multiplier:.1f}倍 | {upload_msg}"
        desp = f"![cover]({thumb_url})\n\n### [{title}]({url})\n\n{body_text}\n\n[点击跳转]({url})"
        requests.post(base_url, data={"title": title_short, "desp": desp})
        
    else:
        # Bark
        post_url = f"https://api.day.app/{PUSH_KEY}"
        params = {
            "title": "黑马视频自动处理完成",
            "body": f"{title}\n{body_text}",
            "url": url,
            "icon": thumb_url,
            "group": "BlackHorse"
        }
        requests.post(post_url, data=params)

    print(f"Notification sent for: {title}")

# --- Main CLI ---

def main():
    cleanup_dirs()
    service = get_service()
    
    # 1. Search
    search_results = search_videos(service)
    print(f"Found {len(search_results)} candidates.")
    
    video_ids = [item['id']['videoId'] for item in search_results]
    
    # 2. Details (Views + Duration)
    video_details = get_video_details(service, video_ids)
    
    # 3. Channel Stats
    channel_ids = [item['snippet']['channelId'] for item in video_details]
    channel_map = get_channel_details(service, channel_ids)
    
    found_count = 0
    for video in video_details:
        v_stats = video['statistics']
        c_id = video['snippet']['channelId']
        c_details = video['contentDetails']
        
        views = int(v_stats.get('viewCount', 0))
        subs = channel_map.get(c_id, 999999)
        
        # Duration Check
        duration_iso = c_details.get('duration', 'PT0S')
        duration_sec = parse_duration(duration_iso)
        
        # 4. Filter Logic
        if subs < MAX_SUBS and views > MIN_VIEWS:
            if duration_sec > MAX_DURATION_SEC:
                print(f"[SKIP] Duration {duration_sec}s > {MAX_DURATION_SEC}s: {video['snippet']['title']}")
                continue
            
            if subs == 0: subs = 1
            multiplier = views / subs
            
            title = video['snippet']['title']
            video_id = video['id']
            url = f"https://www.youtube.com/watch?v={video_id}"
            thumb_url = video['snippet']['thumbnails'].get('high', {}).get('url', '')
            
            print(f"[MATCH] {title} (Views:{views}, Subs:{subs}, Mult:{multiplier:.1f}x)")
            
            # --- Auto Process Pipeline ---
            local_file = download_video(url, video_id)
            uploaded = False
            
            if local_file:
                processed_file = process_video(local_file, video_id)
                if processed_file:
                    file_id = upload_to_aliyun(processed_file)
                    if file_id:
                        uploaded = True
            
            send_push(title, url, views, subs, multiplier, thumb_url, uploaded)
            found_count += 1
            
    print(f"Done. Processed {found_count} videos.")

if __name__ == "__main__":
    main()
