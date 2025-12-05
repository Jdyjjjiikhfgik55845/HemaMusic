# Copyright (c) 2025 TheHamkerAlone 
# Licensed under the MIT License.
# This file is part of AloneXMusic


import os
import re
import yt_dlp
import random
import asyncio
import aiohttp
from pathlib import Path
from typing import Optional, Union

from pyrogram import enums, types
from py_yt import Playlist, VideosSearch

from AloneX import config, logger
from AloneX.helpers import Track, utils


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookies = []
        self.checked = False
        self.warned = False
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )

    def get_cookies(self):
        if not self.checked:
            for file in os.listdir("AloneX/cookies"):
                if file.endswith(".txt"):
                    self.cookies.append(file)
            self.checked = True
        if not self.cookies:
            if not self.warned:
                self.warned = True
                logger.warning("Cookies are missing; downloads might fail.")
            return None
        return f"AloneX/cookies/{random.choice(self.cookies)}"

    async def save_cookies(self, urls: list[str]) -> None:
        logger.info("Saving cookies from urls...")
        async with aiohttp.ClientSession() as session:
            for url in urls:
                path = f"AloneX/cookies/cookie{random.randint(10000, 99999)}.txt"
                link = url.replace("me/", "me/raw/")
                async with session.get(link) as resp:
                    resp.raise_for_status()
                    with open(path, "wb") as fw:
                        fw.write(await resp.read())
        logger.info("Cookies saved.")

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def url(self, message_1: types.Message) -> Union[str, None]:
        messages = [message_1]
        link = None
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)

        for message in messages:
            text = message.text or message.caption or ""

            if message.entities:
                for entity in message.entities:
                    if entity.type == enums.MessageEntityType.URL:
                        link = text[entity.offset : entity.offset + entity.length]
                        break

            if message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == enums.MessageEntityType.TEXT_LINK:
                        link = entity.url
                        break

        if link:
            return link.split("&si")[0].split("?si")[0]
        return None

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        _search = VideosSearch(query, limit=1)
        results = await _search.next()
        if results and results["result"]:
            data = results["result"][0]
            return Track(
                id=data.get("id"),
                channel_name=data.get("channel", {}).get("name"),
                duration=data.get("duration"),
                duration_sec=utils.to_seconds(data.get("duration")),
                message_id=m_id,
                title=data.get("title")[:25],
                thumbnail=data.get("thumbnails", [{}])[-1].get("url").split("?")[0],
                url=data.get("link"),
                view_count=data.get("viewCount", {}).get("short"),
                video=video,
            )
        return None

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track | None]:
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in plist["videos"][:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails")[-1].get("url").split("?")[0],
                    url=data.get("link").split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except:
            pass
        return tracks

    async def download_with_api(self, video_id: str, video: bool = False) -> Optional[str]:
        """Download using external API"""
        api_url = config.VIDEO_API_URL if video else config.API_URL
        api_key = getattr(config, 'API_KEY', None)
        
        if not api_url or not api_key:
            return None
            
        endpoint = f"{api_url}/{'video' if video else 'song'}/{video_id}?api={api_key}"
        
        async with aiohttp.ClientSession() as session:
            for attempt in range(10):
                try:
                    async with session.get(endpoint) as response:
                        if response.status != 200:
                            raise Exception(f"API request failed with status {response.status}")
                        
                        data = await response.json()
                        status = data.get("status", "").lower()
                        
                        if status == "done":
                            download_url = data.get("link")
                            if not download_url:
                                raise Exception("No download URL in API response")
                                
                            file_format = data.get("format", "mp4" if video else "mp3")
                            file_path = f"downloads/{video_id}.{file_format}"
                            
                            async with session.get(download_url) as file_response:
                                with open(file_path, 'wb') as f:
                                    while True:
                                        chunk = await file_response.content.read(8192)
                                        if not chunk:
                                            break
                                        f.write(chunk)
                            return file_path
                            
                        elif status == "downloading":
                            await asyncio.sleep(4 if not video else 8)
                        else:
                            error_msg = data.get("error") or data.get("message") or f"Unexpected status '{status}'"
                            raise Exception(f"API error: {error_msg}")
                            
                except Exception as e:
                    logger.error(f"API download attempt {attempt + 1} failed: {e}")
                    if attempt == 9:
                        return None
                    await asyncio.sleep(2)
        return None

    async def download(self, video_id: str, video: bool = False) -> Optional[str]:
        url = self.base + video_id
        ext = "mp4" if video else "webm"
        filename = f"downloads/{video_id}.{ext}"

        if Path(filename).exists():
            return filename

        # Try API download first if configured
        if hasattr(config, 'API_URL') and hasattr(config, 'API_KEY'):
            try:
                api_result = await self.download_with_api(video_id, video)
                if api_result:
                    return api_result
            except Exception as e:
                logger.error(f"API download failed, falling back to cookies: {e}")

        # Fallback to cookie-based download
        cookie = self.get_cookies()
        base_opts = {
            "outtmpl": "downloads/%(id)s.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "geo_bypass": True,
            "no_warnings": True,
            "overwrites": False,
            "nocheckcertificate": True,
            "cookiefile": cookie,
        }

        if video:
            ydl_opts = {
                **base_opts,
                "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio)",
                "merge_output_format": "mp4",
            }
        else:
            ydl_opts = {
                **base_opts,
                "format": "bestaudio[ext=webm][acodec=opus]",
            }

        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    ydl.download([url])
                except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError):
                    if cookie and cookie in self.cookies:
                        self.cookies.remove(cookie)
                    return None
                except Exception as ex:
                    logger.error("Download failed: %s", ex)
                    return None
            return filename

        return await asyncio.to_thread(_download)