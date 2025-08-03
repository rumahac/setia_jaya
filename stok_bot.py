import os
import sqlite3
from datetime import datetime, time
from telegram import Update, InputMediaPhoto
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, JobQueue
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import pytz
import requests
from threading import Timer

# Konfigurasi
TOKEN = os.getenv('8282082679:AAGfvNm9EhpudLhbhqxQk1z-LSPITbi8dYM') or '8282082679:AAGfvNm9EhpudLhbhqxQk1z-LSPITbi8dYM'
ADMIN_IDS = [5036291155]  # Ganti dengan ID admin Anda
TIMEZONE = pytz.timezone('Asia/Jakarta')
MIN_STOCK = 5  # Batas minimum stok untuk notifikasi

class StokBot:
    def __init__(self):
        self.init_db()
        self.updater = Updater(TOKEN, use_context=True)
        self.dp = self.updater.dispatcher
        self.job_queue = self.updater.job_queue
        
        # Handler
        handlers = [
            CommandHandler("start", self.start),
            CommandHandler("tambah", self.tambah),
            CommandHandler("list", self.list_barang),
            CommandHandler("edit", self.edit),
            CommandHandler("hapus", self.hapus),
            CommandHandler("keluar", self.barang_keluar),
            CommandHandler("test_notif", self.test_notifikasi),
            MessageHandler(Filters.photo, self.handle_image),
            MessageHandler(Filters.text & ~Filters.command, self.handle_text)
        ]
        for handler in handlers:
            self.dp.add_handler(handler)
        
        self.dp.add_error_handler(self.error_handler)
        self.schedule_daily_notification()

    def init_db(self):
        """Inisialisasi database"""
        self.conn = sqlite3.connect('stok.db', check_same_thread=False)
        self.c = self.conn.cursor()
        
        # Tabel barang
        self.c.execute('''CREATE TABLE IF NOT EXISTS barang
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         kode TEXT UNIQUE NOT NULL,
                         nama TEXT NOT NULL,
                         harga INTEGER NOT NULL,
                         stok INTEGER NOT NULL,
                         min_stok INTEGER DEFAULT 5,
                         kategori TEXT,
                         gambar TEXT,
                         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # Tabel transaksi
        self.c.execute('''CREATE TABLE IF NOT EXISTS transaksi
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         barang_id INTEGER NOT NULL,
                         jenis TEXT NOT NULL,
                         jumlah INTEGER NOT NULL,
                         keterangan TEXT,
                         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                         FOREIGN KEY (barang_id) REFERENCES barang(id))''')
        
        # Tabel kategori
        self.c.execute('''CREATE TABLE IF NOT EXISTS kategori
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         nama TEXT UNIQUE NOT NULL)''')
        
        # Data contoh
        self.c.execute("SELECT COUNT(*) FROM kategori")
        if self.c.fetchone()[0] == 0:
            self.c.executemany("INSERT INTO kategori (nama) VALUES (?)", 
                             [('Elektronik',), ('Peralatan',), ('Makanan',)])
            self.conn.commit()

    def schedule_daily_notification(self):
        """Jadwalkan notifikasi harian jam 8 pagi"""
        time_8am = time(8, 0, 0)
        self.job_queue.run_daily(
            self.send_stock_notification,
            time=time_8am,
            days=(0, 1, 2, 3, 4, 5, 6),
            context=None,
            name="daily_stock_notification"
        )

    def send_stock_notification(self, context: CallbackContext):
        """Kirim notifikasi stok dengan gambar"""
        self.c.execute('''SELECT id, kode, nama, stok, min_stok, gambar 
                         FROM barang 
                         WHERE stok <= min_stok''')
        low_stock_items = self.c.fetchall()
        
        if not low_stock_items:
            for admin_id in ADMIN_IDS:
                context.bot.send_message(
                    chat_id=admin_id,
                    text="🔄 Laporan Stok Pagi Ini:\n\n✅ Semua barang stoknya aman"
                )
            return
        
        # Buat pesan dan gambar
        message = "⚠️ LAPORAN STOK HABIS/CRITIS ⚠️\n\n"
        media_group = []
        
        for idx, (barang_id, kode, nama, stok, min_stok, gambar) in enumerate(low_stock_items, 1):
            message += f"{idx}. {nama} ({kode})\n   Stok: {stok} (Minimal: {min_stok})\n\n"
            
            # Tambahkan gambar jika ada
            img_path = gambar if os.path.exists(gambar) else 'no_image.jpg'
            caption = f"{nama}\nStok: {stok} (Min: {min_stok})"
            
            if idx <= 10:  # Maksimal 10 gambar per pesan
                with open(img_path, 'rb') as photo:
                    media_group.append(InputMediaPhoto(photo, caption=caption if idx == 1 else ""))
        
        message += "Segera lakukan restock!"
        
        # Kirim ke admin
        for admin_id in ADMIN_IDS:
            if media_group:
                context.bot.send_media_group(
                    chat_id=admin_id,
                    media=media_group
                )
            context.bot.send_message(
                chat_id=admin_id,
                text=message
            )

    def test_notifikasi(self, update: Update, context: CallbackContext):
        """Trigger manual untuk testing notifikasi"""
        if update.effective_user.id not in ADMIN_IDS:
            update.message.reply_text("❌ Hanya admin yang bisa melakukan ini")
            return
            
        update.message.reply_text("🔄 Memulai test notifikasi...")
        self.send_stock_notification(context)

    def barang_keluar(self, update: Update, context: CallbackContext):
        """Handler command /keluar"""
        if update.effective_user.id not in ADMIN_IDS:
            update.message.reply_text("❌ Hanya admin yang bisa mencatat barang keluar")
            return
            
        update.message.reply_text(
            "📤 Catat Barang Keluar\n\n"
            "Silakan kirim dengan format:\n"
            "Kode Barang\nJumlah\nKeterangan (optional)\n\n"
            "Contoh:\nBRG001\n5\nPenjualan ke Toko ABC"
        )
        context.user_data['state'] = 'barang_keluar'

    def process_barang_keluar(self, update: Update, context: CallbackContext, data: list):
        """Proses transaksi barang keluar"""
        try:
            if len(data) < 2:
                update.message.reply_text("❌ Format salah. Minimal kode dan jumlah")
                return
            
            kode = data[0].strip()
            jumlah = int(data[1].strip())
            keterangan = data[2].strip() if len(data) > 2 else "Barang keluar"
            
            # Cek stok
            self.c.execute("SELECT id, nama, stok, gambar FROM barang WHERE kode = ?", (kode,))
            barang = self.c.fetchone()
            
            if not barang:
                update.message.reply_text(f"❌ Barang dengan kode {kode} tidak ditemukan")
                return
                
            barang_id, nama, stok, gambar = barang
            
            if jumlah > stok:
                update.message.reply_text(
                    f"❌ Stok tidak mencukupi!\n"
                    f"Stok {nama} tersedia: {stok}\n"
                    f"Permintaan: {jumlah}"
                )
                return
            
            # Update stok
            self.c.execute("UPDATE barang SET stok = stok - ? WHERE id = ?", 
                          (jumlah, barang_id))
            
            # Catat transaksi
            self.c.execute('''INSERT INTO transaksi 
                            (barang_id, jenis, jumlah, keterangan) 
                            VALUES (?, ?, ?, ?)''',
                         (barang_id, 'keluar', jumlah, keterangan))
            
            self.conn.commit()
            
            # Buat gambar konfirmasi
            img_path = self.generate_keluar_image(barang_id, nama, kode, jumlah, stok - jumlah, gambar)
            
            # Kirim konfirmasi
            update.message.reply_photo(
                open(img_path, 'rb'),
                caption=f"✅ Barang keluar berhasil dicatat:\n\n"
                      f"📦 {nama}\n"
                      f"🆔 {kode}\n"
                      f"📤 Jumlah keluar: {jumlah}\n"
                      f"🛒 Stok tersisa: {stok - jumlah}\n"
                      f"📝 Keterangan: {keterangan}"
            )
            
        except ValueError:
            update.message.reply_text("❌ Jumlah harus berupa angka")
        except Exception as e:
            print(f"Error: {e}")
            update.message.reply_text("❌ Terjadi kesalahan. Silakan coba lagi.")

    def generate_keluar_image(self, barang_id, nama, kode, jumlah_keluar, stok_sisa, gambar_path):
        """Generate gambar konfirmasi barang keluar"""
        # Buka gambar asli atau gambar default
        try:
            img = Image.open(gambar_path if os.path.exists(gambar_path) else 'no_image.jpg')
        except:
            img = Image.new('RGB', (400, 400), color=(200, 200, 200))
        
        width, height = img.size
        new_height = height + 220
        new_img = Image.new('RGB', (width, new_height), color=(240, 240, 240))
        new_img.paste(img, (0, 0))
        
        # Tambahkan teks
        draw = ImageDraw.Draw(new_img)
        try:
            font_large = ImageFont.truetype("arial.ttf", 24)
            font_normal = ImageFont.truetype("arial.ttf", 18)
        except:
            font_large = ImageFont.load_default()
            font_normal = ImageFont.load_default()
        
        # Judul
        draw.text((10, height + 10), "BARANG KELUAR", fill="red", font=font_large)
        
        # Informasi barang
        text_y = height + 50
        draw.text((10, text_y), f"📦 {nama}", fill="black", font=font_normal)
        draw.text((10, text_y + 30), f"🆔 {kode}", fill="black", font=font_normal)
        draw.text((10, text_y + 60), f"📤 Keluar: {jumlah_keluar}", fill="black", font=font_normal)
        draw.text((10, text_y + 90), f"🛒 Sisa: {stok_sisa}", fill="black", font=font_normal)
        
        # Footer
        draw.text((10, text_y + 130), f"🕒 {datetime.now().strftime('%d/%m/%Y %H:%M')}", 
                 fill="gray", font=font_normal)
        
        # Simpan gambar
        img_path = f"keluar_{barang_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
        new_img.save(img_path)
        return img_path

    # ... (fungsi-fungsi lainnya seperti sebelumnya)

    def run(self):
        """Start the bot"""
        print("Bot sedang berjalan...")
        print(f"Notifikasi stok akan dikirim setiap jam 8 pagi {TIMEZONE.zone}")
        self.updater.start_polling()
        self.updater.idle()

if __name__ == '__main__':
    # Buat gambar default jika tidak ada
    if not os.path.exists('no_image.jpg'):
        img = Image.new('RGB', (400, 400), color=(200, 200, 200))
        draw = ImageDraw.Draw(img)
        draw.text((100, 180), "Tidak Ada Gambar", fill="black")
        draw.text((80, 220), "Produk Tidak Tersedia", fill="black")
        img.save('no_image.jpg')
    
    bot = StokBot()
    bot.run()
