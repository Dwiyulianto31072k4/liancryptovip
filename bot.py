import asyncio
import logging
import os
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# Konfigurasi logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("telegram_forwarder.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Kredeensial dan konfigurasi dari environment variables
API_ID = int(os.environ.get("API_ID", "28690093"))
API_HASH = os.environ.get("API_HASH", "aa512841e37c5ccb5a8ac494395bb373")
SOURCE_CHANNEL_ID = int(os.environ.get("SOURCE_CHANNEL_ID", "-1002626068320"))
TARGET_CHANNEL_ID = int(os.environ.get("TARGET_CHANNEL_ID", "-1002694678122"))

# Gunakan StringSession dari environment variable
SESSION = os.environ.get("TELETHON_SESSION", "")

async def main():
    # Reconnect loop
    while True:
        try:
            # Gunakan StringSession untuk menghindari database lock
            client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
            
            # Event handler untuk pesan baru
            @client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
            async def handler(event):
                try:
                    message = event.message
                    
                    # Kirim ulang pesan dengan format "Sent By Lian Analyst"
                    if message.text:
                        custom_text = f"Sent By Lian Analyst\n\n{message.text}"
                        await client.send_message(TARGET_CHANNEL_ID, custom_text)
                    elif message.media:
                        await client.send_file(
                            TARGET_CHANNEL_ID, 
                            message.media,
                            caption="Sent By Lian Analyst" + (f"\n\n{message.text}" if message.text else "")
                        )
                    
                    # Log info pesan
                    message_preview = message.text[:50] + "..." if message.text and len(message.text) > 50 else "Media atau pesan tanpa teks"
                    logger.info(f"Pesan berhasil dikirim ulang: {message_preview}")
                    
                except Exception as e:
                    logger.error(f"Error saat mengirim pesan: {str(e)}")
            
            # Connect dan start
            await client.start()
            
            logger.info(f"Bot berhasil diaktifkan. Memantau channel: {SOURCE_CHANNEL_ID}")
            
            # Jalankan hingga disconnected
            await client.run_until_disconnected()
            
        except Exception as e:
            logger.error(f"Error pada client: {str(e)}")
            logger.info("Mencoba reconnect dalam 30 detik...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    # Jalankan main loop
    asyncio.run(main())
