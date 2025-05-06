import asyncio
import logging
import os
import re
import time
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import aiohttp
from dotenv import load_dotenv

# Muat variabel lingkungan dari file .env
load_dotenv()

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

# Files untuk menyimpan kode verifikasi
VERIFICATION_CODE_FILE = "verification_code.txt"
LOG_FILE = "bot_logs.txt"

# Kredeensial dan konfigurasi dari environment variables
API_ID = int(os.environ.get("API_ID", "28690093"))
API_HASH = os.environ.get("API_HASH", "aa512841e37c5ccb5a8ac494395bb373")
SOURCE_CHANNEL_ID = int(os.environ.get("SOURCE_CHANNEL_ID", "-1002051092635"))
TARGET_CHANNEL_ID = int(os.environ.get("TARGET_CHANNEL_ID", "-4634673046"))
SESSION = os.environ.get("TELETHON_SESSION", "")
PHONE_NUMBER = os.environ.get("PHONE_NUMBER", "+6285161054271")

# Fungsi untuk menulis log ke file
def write_log(message, is_error=False):
    try:
        with open(LOG_FILE, "a") as f:
            timestamp = datetime.now().strftime("%H:%M:%S")
            f.write(f"{timestamp} - {'ERROR' if is_error else 'INFO'} - {message}\n")
    except Exception as e:
        logger.error(f"Failed to write log to file: {str(e)}")

# Fungsi untuk mendapatkan kode verifikasi
def code_callback():
    logger.info("Waiting for verification code...")
    # Hapus file kode verifikasi jika ada
    if os.path.exists(VERIFICATION_CODE_FILE):
        os.remove(VERIFICATION_CODE_FILE)
    
    # Tulis pesan ke log
    write_log("Bot memerlukan kode verifikasi. Silakan masukkan kode verifikasi di Telegram.")
    
    # Tunggu sampai kode verifikasi dimasukkan
    while not os.path.exists(VERIFICATION_CODE_FILE):
        time.sleep(1)
    
    # Baca kode verifikasi
    with open(VERIFICATION_CODE_FILE, "r") as f:
        code = f.read().strip()
    
    # Hapus file setelah dibaca
    os.remove(VERIFICATION_CODE_FILE)
    
    write_log(f"Kode verifikasi diterima: {code}")
    return code

# Fungsi untuk menghitung persentase perubahan
def calculate_percentage_change(entry_price, target_price):
    try:
        entry = float(entry_price)
        target = float(target_price)
        
        # Validasi untuk mencegah pembagian dengan nol atau nilai yang terlalu kecil
        if entry < 0.0001:
            logger.warning(f"Entry price terlalu kecil: {entry}, gunakan default")
            return 0.0
            
        percentage = ((target - entry) / entry) * 100
        
        # Batasi persentase maksimum ke nilai yang wajar
        if abs(percentage) > 1000:
            logger.warning(f"Percentage terlalu besar: {percentage}, dibatasi ke ±1000%")
            percentage = 1000.0 if percentage > 0 else -1000.0
            
        return percentage
    except (ValueError, ZeroDivisionError):
        logger.error(f"Error menghitung persentase: {entry_price}, {target_price}")
        return 0.0

# Fungsi untuk mendapatkan harga cryptocurrency saat ini
async def get_current_price(coin_symbol):
    try:
        # Hapus akhiran USDT jika ada
        base_symbol = coin_symbol.replace('USDT', '')
        
        # Coba API Binance terlebih dahulu
        binance_url = f"https://api.binance.com/api/v3/ticker/price?symbol={coin_symbol}"
        async with aiohttp.ClientSession() as session:
            async with session.get(binance_url) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'price' in data:
                        return float(data['price'])
                
        # Fallback ke CoinGecko
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={base_symbol.lower()}&vs_currencies=usd"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if base_symbol.lower() in data:
                        return data[base_symbol.lower()]['usd']
                
        return None
    except Exception as e:
        logger.error(f"Error mendapatkan harga: {str(e)}")
        return None

# Fungsi untuk membuat tabel persentase perubahan
def create_percentage_table(coin_name, entry_price, targets, stop_losses):
    try:
        # Header tabel
        table = "📝 Kalkulasi Persentase Perubahan Harga\n\n"
        table += "Level         Harga       % Perubahan dari Entry\n"
        table += "------------------------------------------------\n"
        
        # Tambahkan target
        for i, target in enumerate(targets, 1):
            percentage = calculate_percentage_change(entry_price, target)
            table += f"Target {i}      {target}      +{percentage:.2f}%\n"
        
        # Tambahkan stop loss
        for i, sl in enumerate(stop_losses, 1):
            percentage = calculate_percentage_change(entry_price, sl)
            # Gunakan nilai persentase aktual (mungkin negatif)
            sign = "+" if percentage >= 0 else ""
            table += f"Stop Loss {i}    {sl}      {sign}{percentage:.2f}%\n"
        
        return table
    except Exception as e:
        logger.error(f"Error membuat tabel persentase: {str(e)}")
        return "Error membuat tabel persentase."

# Fungsi untuk mendeteksi tipe pesan dengan pattern matching yang lebih baik
def detect_message_type(text):
    # Cek untuk Daily Recap
    if re.search(r'Daily\s+Results|每日結算統計|Results', text, re.IGNORECASE):
        return "DAILY_RECAP"
    
    # Cek apakah ini pesan multi-target hit (berisi beberapa target dengan tanda ceklis)
    target_checkmarks = re.findall(r'Target\s+\d+.*?[✅🟢]', text, re.IGNORECASE)
    if len(target_checkmarks) > 1:
        return "MULTI_TARGET_HIT"
    
    # Cek untuk Target Hit tunggal
    if (re.search(r'Hitted\s+target|Reached\s+target', text, re.IGNORECASE) or 
        re.search(r'Target\s+\d+.*?[✅🟢]', text, re.IGNORECASE) or
        re.search(r'Target\s+\d+\s*[:]\s*\d+.*?[✅🟢]', text, re.IGNORECASE)):
        return "TARGET_HIT"
    
    # Cek untuk Stop Loss Hit
    if (re.search(r'Hitted\s+stop\s+loss|Stop\s+loss\s+triggered', text, re.IGNORECASE) or
        re.search(r'Stop\s+loss\s+\d+.*?[🛑🔴]', text, re.IGNORECASE) or
        re.search(r'Stop\s+loss\s+\d+\s*[:]\s*\d+.*?[🛑🔴]', text, re.IGNORECASE)):
        return "STOP_LOSS_HIT"
    
    # Cek jika ini adalah pesan sangat singkat dengan hanya nama koin dan target/harga
    if len(text.strip().split('\n')) <= 2 and ('USDT' in text or 'BTC' in text):
        # Jika pesan sangat singkat berisi tanda ceklis, kemungkinan target hit
        if '✅' in text or '🟢' in text:
            return "TARGET_HIT"
        # Jika pesan sangat singkat berisi simbol stop, kemungkinan stop loss
        elif '🛑' in text or '🔴' in text:
            return "STOP_LOSS_HIT"
    
    # Jika tidak ada tipe spesifik terdeteksi, anggap itu sinyal baru
    return "NEW_SIGNAL"

# Fungsi untuk ekstrak data dari pesan
def extract_trading_data(message_text):
    try:
        lines = message_text.split('\n')
        
        # Variabel untuk menyimpan data yang diekstrak
        coin_name = None
        entry_price = None
        targets = []
        stop_losses = []
        
        # Pola untuk ekstrak nama koin (biasanya di baris pertama)
        for line in lines[:3]:  # Cek 3 baris pertama
            line = line.strip()
            if not line:
                continue
                
            # Coba berbagai pola untuk nama koin
            coin_patterns = [
                r'^([A-Za-z0-9]+)[^A-Za-z0-9]',  # Koin di awal baris
                r'([A-Za-z0-9]+USDT)',  # Format seperti BTCUSDT
                r'([A-Za-z0-9]+) NEW'   # Format seperti "COIN NEW"
            ]
            
            for pattern in coin_patterns:
                coin_match = re.search(pattern, line)
                if coin_match:
                    coin_name = coin_match.group(1)
                    break
            
            if coin_name:
                break
        
        # Iterasi per baris untuk ekstrak data
        for line in lines:
            line = line.strip()
            
            # Ekstrak harga entry
            entry_match = re.search(r'Entry:?\s*([0-9.]+)', line)
            if entry_match:
                entry_price = entry_match.group(1)
            
            # Ekstrak harga target
            target_match = re.search(r'Target\s+(\d+):?\s*([0-9.]+)', line)
            if target_match:
                target_num = int(target_match.group(1))
                target_price = target_match.group(2)
                
                # Pastikan list cukup panjang
                while len(targets) < target_num:
                    targets.append(None)
                
                # Simpan target di posisi yang benar (indeks dimulai dari 0)
                targets[target_num-1] = target_price
            
            # Ekstrak stop loss
            sl_match = re.search(r'Stop\s+loss\s+(\d+):?\s*([0-9.]+)', line, re.IGNORECASE)
            if sl_match:
                sl_num = int(sl_match.group(1))
                sl_price = sl_match.group(2)
                
                # Pastikan list cukup panjang
                while len(stop_losses) < sl_num:
                    stop_losses.append(None)
                
                # Simpan stop loss di posisi yang benar
                stop_losses[sl_num-1] = sl_price
        
        # Hapus nilai None dari list
        targets = [t for t in targets if t is not None]
        stop_losses = [sl for sl in stop_losses if sl is not None]
        
        return {
            'coin_name': coin_name,
            'entry_price': entry_price,
            'targets': targets,
            'stop_losses': stop_losses
        }
    except Exception as e:
        logger.error(f"Error mengekstrak data trading: {str(e)}")
        return {
            'coin_name': None,
            'entry_price': None,
            'targets': [],
            'stop_losses': []
        }

# Fungsi untuk ekstrak data dari pesan target hit/stop loss
def extract_hit_data(message_text):
    # Untuk multi-target hits, ekstrak koin dan semua target
    data = {'coin': None, 'targets': [], 'stop_losses': []}
    
    # Temukan nama koin
    coin_match = re.search(r'([A-Za-z0-9]+)(USDT|BTC|ETH|BNB)', message_text)
    if coin_match:
        data['coin'] = coin_match.group(0)
    
    # Temukan semua level target dan harga
    target_matches = re.findall(r'Target\s+(\d+)[:\s]+([0-9.]+)\s*[✅🟢]', message_text, re.IGNORECASE)
    for target_num, target_price in target_matches:
        data['targets'].append({
            'level': f"Target {target_num}",
            'price': target_price
        })
    
    # Temukan semua level stop loss dan harga
    sl_matches = re.findall(r'Stop\s+loss\s+(\d+)[:\s]+([0-9.]+)\s*[🛑🔴]', message_text, re.IGNORECASE)
    for sl_num, sl_price in sl_matches:
        data['stop_losses'].append({
            'level': f"Stop Loss {sl_num}",
            'price': sl_price
        })
    
    return data

# Fungsi untuk ekstrak data dari daily recap
def extract_daily_recap_data(text):
    data = {
        'date': None,
        'hitted_targets': [],
        'running': [],
        'stop_losses': [],
        'total_signals': 0,
        'hitted_take_profits': 0,
        'hitted_stop_losses': 0
    }
    
    # Ekstrak tanggal
    date_match = re.search(r'(\d{2}/\d{2}-\d{2}/\d{2})', text)
    if date_match:
        data['date'] = date_match.group(1)
    
    # Ekstrak target yang tercapai
    for i in range(1, 5):  # Target 1-4
        target_match = re.search(rf'Hitted\s+target\s+{i}:\s*(.*?)(?:\n|$)', text)
        if target_match:
            coins = [coin.strip() for coin in target_match.group(1).split(',')]
            data['hitted_targets'].append({'level': i, 'coins': coins})
    
    # Ekstrak sinyal yang masih berjalan
    running_match = re.search(r'Running:\s*(.*?)(?:\n|$)', text)
    if running_match:
        data['running'] = [coin.strip() for coin in running_match.group(1).split(',')]
    
    # Ekstrak stop loss
    sl_match = re.search(r'Hitted\s+stop\s+loss:\s*(.*?)(?:\n|$)', text)
    if sl_match:
        data['stop_losses'] = [coin.strip() for coin in sl_match.group(1).split(',')]
    
    # Ekstrak statistik
    total_match = re.search(r'Total\s+Signals:\s*(\d+)', text)
    if total_match:
        data['total_signals'] = int(total_match.group(1))
    
    tp_match = re.search(r'Hitted\s+Take-Profits:\s*(\d+)', text)
    if tp_match:
        data['hitted_take_profits'] = int(tp_match.group(1))
    
    sl_count_match = re.search(r'Hitted\s+Stop-Losses:\s*(\d+)', text)
    if sl_count_match:
        data['hitted_stop_losses'] = int(sl_count_match.group(1))
    
    return data

# Fungsi untuk membuat tabel win rate
def create_win_rate_table(recap_data):
    total_signals = recap_data['total_signals']
    take_profits = recap_data['hitted_take_profits']
    stop_losses = recap_data['hitted_stop_losses']
    
    if total_signals == 0:
        win_rate = 0
    else:
        win_rate = (take_profits / total_signals) * 100
    
    table = "📊 Analisis Performa Trading 📊\n\n"
    table += "Metrik                  Nilai       Persentase\n"
    table += "--------------------------------------------\n"
    table += f"Win Rate               {take_profits}/{total_signals}     {win_rate:.2f}%\n"
    
    if take_profits + stop_losses > 0:
        profit_ratio = (take_profits / (take_profits + stop_losses)) * 100
        table += f"Rasio Profit/Loss      {take_profits}/{stop_losses}     {profit_ratio:.2f}%\n"
    
    table += f"Sinyal Berjalan        {len(recap_data['running'])}         {(len(recap_data['running'])/total_signals*100):.2f}%\n"
    
    return table

# Fungsi utama untuk menjalankan bot
async def main():
    # Reconnect loop
    while True:
        try:
            # Buat client
            if SESSION:
                client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
                logger.info("Menggunakan StringSession yang sudah ada")
            else:
                # Gunakan pengaturan sesi file pada awal penggunaan
                client = TelegramClient('telegram_forwarder_session', API_ID, API_HASH)
                logger.info("Membuat sesi baru, mungkin memerlukan verifikasi")
            
            # Event handler untuk pesan baru
            @client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
            async def handler(event):
                try:
                    message = event.message
                    
                    # Jika tidak ada teks, kirim media saja
                    if not message.text:
                        if message.media:
                            await client.send_file(
                                TARGET_CHANNEL_ID, 
                                message.media,
                                caption=f"🚀 VIP SIGNAL 🚀\n\n"
                            )
                        return
                    
                    # Log pesan masuk untuk debugging
                    logger.info(f"Menerima pesan: {message.text[:100]}...")
                    
                    # Deteksi tipe pesan
                    message_type = detect_message_type(message.text)
                    logger.info(f"Tipe pesan terdeteksi: {message_type}")
                    
                    if message_type == "DAILY_RECAP":
                        # Proses daily recap
                        recap_data = extract_daily_recap_data(message.text)
                        
                        # Buat teks dengan win rate
                        custom_text = f"📅 DAILY RECAP: {recap_data['date'] if recap_data['date'] else 'Hari Ini'} 📅\n\n"
                        custom_text += message.text + "\n\n"
                        custom_text += create_win_rate_table(recap_data)
                        custom_text += "\n\n"
                        
                        # Kirim pesan
                        await client.send_message(TARGET_CHANNEL_ID, custom_text)
                    
                    elif message_type == "MULTI_TARGET_HIT":
                        # Proses pesan dengan beberapa target hits
                        hit_data = extract_hit_data(message.text)
                        
                        if hit_data['coin'] and hit_data['targets']:
                            # Buat pesan update dengan semua target yang tercapai
                            custom_text = f"✅ SIGNAL UPDATE: {hit_data['coin']} ✅\n\n"
                            
                            # Tambahkan semua target yang tercapai
                            for target in hit_data['targets']:
                                custom_text += f"🎯 {target['level']} ({target['price']}) HIT!\n"
                            
                            custom_text += "\n"
                        else:
                            # Jika ekstraksi gagal, kirim pesan asli dengan header standar
                            custom_text = f"✅ SIGNAL UPDATE ✅\n\n"
                            custom_text += message.text + "\n\n"
                        
                        await client.send_message(TARGET_CHANNEL_ID, custom_text)
                    
                    elif message_type == "TARGET_HIT":
                        # Format khusus untuk target hit tunggal
                        hit_data = extract_hit_data(message.text)
                        
                        if hit_data['coin'] and len(hit_data['targets']) > 0:
                            # Gunakan format "SIGNAL UPDATE" untuk target hit
                            custom_text = f"✅ SIGNAL UPDATE: {hit_data['coin']} ✅\n\n"
                            custom_text += f"🎯 {hit_data['targets'][0]['level']} ({hit_data['targets'][0]['price']}) HIT!\n\n"
                        else:
                            # Jika ekstraksi gagal, kirim pesan asli dengan header standar
                            custom_text = f"✅ SIGNAL UPDATE ✅\n\n"
                            custom_text += message.text + "\n\n"
                        
                        await client.send_message(TARGET_CHANNEL_ID, custom_text)
                        
                    elif message_type == "STOP_LOSS_HIT":
                        # Format khusus untuk stop loss hit
                        hit_data = extract_hit_data(message.text)
                        
                        if hit_data['coin'] and len(hit_data['stop_losses']) > 0:
                            # Gunakan format "SIGNAL UPDATE" untuk stop loss hit
                            custom_text = f"🔴 SIGNAL UPDATE: {hit_data['coin']} 🔴\n\n"
                            custom_text += f"⚠️ {hit_data['stop_losses'][0]['level']} ({hit_data['stop_losses'][0]['price']}) TRIGGERED!\n\n"
                        else:
                            # Jika ekstraksi gagal, kirim pesan asli dengan header standar
                            custom_text = f"🔴 SIGNAL UPDATE 🔴\n\n"
                            custom_text += message.text + "\n\n"
                        
                        await client.send_message(TARGET_CHANNEL_ID, custom_text)
                        
                    else:  # NEW_SIGNAL
                        # Ekstrak data trading
                        trading_data = extract_trading_data(message.text)
                        coin_name = trading_data['coin_name']
                        entry_price = trading_data['entry_price']
                        targets = trading_data['targets']
                        stop_losses = trading_data['stop_losses']
                        
                        # Jika tidak ada harga entry tapi punya nama koin, coba dapatkan harga saat ini
                        if coin_name and not entry_price and (targets or stop_losses):
                            current_price = await get_current_price(coin_name)
                            if current_price:
                                entry_price = str(current_price)
                                logger.info(f"Menggunakan harga saat ini untuk {coin_name}: {entry_price}")
                        
                        # Buat pesan kustom
                        if coin_name and entry_price and (targets or stop_losses):
                            # Header
                            custom_text = f"🚀 VIP SIGNAL: {coin_name} 🚀\n\n"
                            
                            # Tambahkan pesan asli
                            custom_text += message.text + "\n\n"
                            
                            # Tambahkan tabel persentase jika data cukup
                            if targets or stop_losses:
                                custom_text += create_percentage_table(coin_name, entry_price, targets, stop_losses)
                            
                            # Footer
                            custom_text += "\n\n"
                        else:
                            # Format default jika data tidak lengkap
                            custom_text = f"🚀 VIP SIGNAL 🚀\n\n{message.text}\n\n "
                        
                        # Kirim pesan ke channel target
                        await client.send_message(TARGET_CHANNEL_ID, custom_text)
                    
                    # Log info pesan
                    message_preview = message.text[:50] + "..." if message.text and len(message.text) > 50 else "Media atau pesan tanpa teks"
                    log_msg = f"Pesan berhasil diteruskan: {message_preview}"
                    logger.info(log_msg)
                    write_log(log_msg)
                        
                except Exception as e:
                    error_msg = f"Error mengirim pesan: {str(e)}"
                    logger.error(error_msg)
                    write_log(error_msg, True)
            
            # Mulai client
            write_log("Memulai client Telegram...")
            
            # Mulai client dengan nomor telepon jika tidak ada SESSION
            if SESSION:
                await client.start()
            else:
                await client.start(PHONE_NUMBER, code_callback=code_callback)
                
                # Simpan sesi untuk penggunaan selanjutnya
                session_str = client.session.save()
                logger.info(f"Sesi baru dibuat: {session_str[:10]}...")
                write_log("Sesi StringSession baru telah dibuat. Salin ke variabel lingkungan TELETHON_SESSION.")
            
            log_msg = f"Bot berhasil diaktifkan. Memantau channel: {SOURCE_CHANNEL_ID}"
            logger.info(log_msg)
            write_log(log_msg)
            
            # Jalankan hingga terputus
            await client.run_until_disconnected()
            
        except Exception as e:
            error_msg = f"Error pada client: {str(e)}"
            logger.error(error_msg)
            write_log(error_msg, True)
            logger.info("Mencoba menghubungkan kembali dalam 30 detik...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    # Jalankan main loop
    asyncio.run(main())
