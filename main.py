"""
🤖 Water Bill Bot - النسخة الكاملة المحسنة
بوت تلجرام متكامل لحساب فواتير المياه مع جميع التحسينات
"""

import json
import datetime
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# تحميل المتغيرات البيئية
load_dotenv()

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ============ الإعدادات ============
# الحصول على المسار الحالي للملف
BASE_DIR = Path(__file__).resolve().parent
TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = str(BASE_DIR / "readings.json")
BACKUP_DIR = str(BASE_DIR / "backups")
UNIT_PRICE = 700
MONTHLY_FEE = 250
CURRENCY = "﷼"

# إعدادات التذكير
REMINDER_DAY = 1  # يوم 1 من كل شهر
REMINDER_HOUR = 13  # الساعة 13
REMINDER_MINUTE = 55  # الدقيقة 55 - تم التعديل حسب طلب المستخدم
SECOND_REMINDER_DAY = 25 # التذكير الثاني يوم 25

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# ============ هياكل البيانات ============
@dataclass
class Invoice:
    """هيكل بيانات الفاتورة"""
    user_id: str
    year_month: str
    previous_reading: float
    current_reading: float
    consumption: float
    total_amount: float
    timestamp: str
    month_name: str = ""

@dataclass
class UserSettings:
    """إعدادات المستخدم"""
    user_id: str
    first_name: str = ""
    username: str = ""
    reminder_enabled: bool = True
    notification_time: str = "10:00"
    created_at: str = ""

@dataclass 
class ConsumptionTier:
    """شرائح الاستهلاك (للتوسع المستقبلي)"""
    min_units: float = 0
    max_units: float = float('inf')
    price_per_unit: float = UNIT_PRICE

# ============ مدير البيانات ============
class DataManager:
    """مدير كامل للبيانات باستخدام JSON"""
    
    def __init__(self, data_file: str = DATA_FILE):
        self.data_file = data_file
        self.backup_dir = BACKUP_DIR
        self.ensure_directories()
        self.data = self.load_data()
    
    def ensure_directories(self):
        """تأكد من وجود المجلدات اللازمة"""
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir)
    
    def load_data(self) -> Dict:
        """تحميل البيانات من ملف JSON"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info(f"تم تحميل البيانات من {self.data_file}")
                    return data
            except json.JSONDecodeError as e:
                logger.error(f"خطأ في تحليل JSON: {e}")
                # إنشاء ملف جديد إذا كان تالفاً
                self.create_backup_before_fix()
                return self.initialize_data_structure()
            except Exception as e:
                logger.error(f"خطأ في تحميل البيانات: {e}")
                return self.initialize_data_structure()
        else:
            logger.info(f"إنشاء ملف بيانات جديد: {self.data_file}")
            return self.initialize_data_structure()
    
    def initialize_data_structure(self) -> Dict:
        """تهيئة هيكل البيانات الجديد"""
        return {
            "version": "2.0",
            "created_at": datetime.datetime.now().isoformat(),
            "users": {},
            "invoices": {},
            "settings": {
                "unit_price": UNIT_PRICE,
                "monthly_fee": MONTHLY_FEE,
                "currency": CURRENCY,
                "reminder_day": REMINDER_DAY,
                "reminder_hour": REMINDER_HOUR
            }
        }
    
    def save_data(self):
        """حفظ البيانات إلى ملف JSON مع نسخة احتياطية"""
        try:
            # حفظ نسخة احتياطية قبل الكتابة
            self.create_auto_backup()
            
            # كتابة البيانات الجديدة
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            
            logger.info("تم حفظ البيانات بنجاح")
            
        except Exception as e:
            logger.error(f"خطأ في حفظ البيانات: {e}")
            raise
    
    def get_user(self, user_id: str) -> Dict:
        """الحصول على بيانات مستخدم مع إنشاء إذا لم يكن موجوداً"""
        if user_id not in self.data["users"]:
            self.data["users"][user_id] = {
                "first_name": "",
                "username": "",
                "reminder_enabled": True,
                "notification_time": "10:00",
                "created_at": datetime.datetime.now().isoformat(),
                "last_active": datetime.datetime.now().isoformat()
            }
        return self.data["users"][user_id]
    
    def update_user(self, user_id: str, user_data: Dict):
        """تحديث بيانات المستخدم"""
        current_data = self.get_user(user_id)
        current_data.update(user_data)
        current_data["last_active"] = datetime.datetime.now().isoformat()
        self.save_data()
    
    def save_invoice(self, invoice: Invoice) -> str:
        """حفظ فاتورة جديدة وإرجاع ID"""
        user_id = invoice.user_id
        
        # تحديث بيانات المستخدم
        self.get_user(user_id)
        
        # إنشاء ID للفاتورة
        invoice_id = f"{user_id}_{invoice.year_month}"
        
        # حفظ الفاتورة
        if "invoices" not in self.data:
            self.data["invoices"] = {}
        
        self.data["invoices"][invoice_id] = {
            "user_id": invoice.user_id,
            "year_month": invoice.year_month,
            "previous_reading": invoice.previous_reading,
            "current_reading": invoice.current_reading,
            "consumption": invoice.consumption,
            "total_amount": invoice.total_amount,
            "timestamp": invoice.timestamp,
            "month_name": invoice.month_name
        }
        
        # تحديث آخر قراءة للمستخدم
        self.data["users"][user_id]["last_reading"] = invoice.current_reading
        self.data["users"][user_id]["last_invoice_date"] = invoice.year_month
        
        self.save_data()
        return invoice_id
    
    def get_invoice(self, invoice_id: str) -> Optional[Dict]:
        """استرجاع فاتورة بواسطة ID"""
        return self.data.get("invoices", {}).get(invoice_id)
    
    def get_user_invoices(self, user_id: str, limit: int = 12) -> List[Dict]:
        """الحصول على فواتير مستخدم معين"""
        invoices = []
        for inv_id, invoice in self.data.get("invoices", {}).items():
            if invoice["user_id"] == user_id:
                invoices.append(invoice)
        
        # ترتيب تنازلي حسب التاريخ
        invoices.sort(key=lambda x: x["year_month"], reverse=True)
        return invoices[:limit]
    
    def get_invoice_by_month(self, user_id: str, year_month: str) -> Optional[Dict]:
        """استرجاع فاتورة شهر معين لمستخدم"""
        invoice_id = f"{user_id}_{year_month}"
        return self.get_invoice(invoice_id)
    
    def get_last_reading(self, user_id: str) -> Optional[float]:
        """الحصول على آخر قراءة للمستخدم"""
        user_invoices = self.get_user_invoices(user_id, limit=1)
        if user_invoices:
            return user_invoices[0]["current_reading"]
        return None
    
    def get_user_stats(self, user_id: str) -> Dict:
        """الحصول على إحصائيات المستخدم"""
        invoices = self.get_user_invoices(user_id, limit=100)
        
        if not invoices:
            return {
                "total_invoices": 0,
                "total_consumption": 0,
                "total_amount": 0,
                "avg_consumption": 0,
                "first_invoice": None,
                "last_invoice": None
            }
        
        total_consumption = sum(inv["consumption"] for inv in invoices)
        total_amount = sum(inv["total_amount"] for inv in invoices)
        
        return {
            "total_invoices": len(invoices),
            "total_consumption": total_consumption,
            "total_amount": total_amount,
            "avg_consumption": total_consumption / len(invoices) if invoices else 0,
            "first_invoice": min(invoices, key=lambda x: x["year_month"])["year_month"] if invoices else None,
            "last_invoice": max(invoices, key=lambda x: x["year_month"])["year_month"] if invoices else None
        }
    
    def get_all_users_for_reminder(self) -> List[Tuple[str, Dict]]:
        """الحصول على جميع المستخدمين المفعل لديهم التذكيرات"""
        users_for_reminder = []
        for user_id, user_data in self.data.get("users", {}).items():
            if user_data.get("reminder_enabled", True):
                users_for_reminder.append((user_id, user_data))
        return users_for_reminder
    
    def create_backup(self, backup_type: str = "manual"):
        """إنشاء نسخة احتياطية"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(
            self.backup_dir, 
            f"water_bill_backup_{backup_type}_{timestamp}.json"
        )
        
        try:
            with open(backup_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"تم إنشاء نسخة احتياطية: {backup_file}")
            
            # تنظيف النسخ القديمة (تبقى آخر 10 نسخ فقط)
            self.cleanup_old_backups()
            
            return backup_file
            
        except Exception as e:
            logger.error(f"فشل إنشاء نسخة احتياطية: {e}")
            return None
    
    def create_auto_backup(self):
        """إنشاء نسخة احتياطية تلقائية"""
        # إنشاء نسخة احتياطية يومية واحدة فقط
        today = datetime.datetime.now().strftime("%Y%m%d")
        backup_exists = any(today in f for f in os.listdir(self.backup_dir) 
                          if f.startswith("water_bill_backup_auto_"))
        
        if not backup_exists:
            self.create_backup("auto")
    
    def create_backup_before_fix(self):
        """نسخة احتياطية قبل إصلاح الملف التالف"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        corrupted_file = os.path.join(
            self.backup_dir,
            f"corrupted_data_{timestamp}.json"
        )
        
        if os.path.exists(self.data_file):
            try:
                import shutil
                shutil.copy2(self.data_file, corrupted_file)
                logger.warning(f"تم حفظ الملف التالف في: {corrupted_file}")
            except Exception as e:
                logger.error(f"فشل حفظ الملف التالف: {e}")
    
    def cleanup_old_backups(self, keep_last: int = 10):
        """حذف النسخ الاحتياطية القديمة"""
        try:
            backup_files = [
                f for f in os.listdir(self.backup_dir) 
                if f.startswith("water_bill_backup_") and f.endswith(".json")
            ]
            
            if len(backup_files) > keep_last:
                backup_files.sort(key=lambda x: os.path.getmtime(
                    os.path.join(self.backup_dir, x)
                ))
                
                for old_file in backup_files[:-keep_last]:
                    os.remove(os.path.join(self.backup_dir, old_file))
                    logger.info(f"تم حذف النسخة القديمة: {old_file}")
                    
        except Exception as e:
            logger.error(f"فشل تنظيف النسخ القديمة: {e}")

# ============ البوت الرئيسي ============
class WaterBillBot:
    """فئة البوت الرئيسية مع جميع الميزات"""
    
    def __init__(self, token: str):
        self.token = token
        self.data_manager = DataManager()
        self.scheduler = AsyncIOScheduler()
        
        # ترجمة الأشهر العربية
        self.arabic_months = [
            "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
            "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"
        ]
        
        # إعداد المهام المجدولة
        # self.setup_scheduler()
    
    def get_arabic_month(self, month_number: int) -> str:
        """تحويل رقم الشهر لاسم عربي"""
        return self.arabic_months[month_number - 1]
    
    def get_arabic_date_from_ym(self, year_month: str) -> str:
        """تحويل YYYY-MM إلى تاريخ عربي"""
        try:
            year, month = map(int, year_month.split("-"))
            month_name = self.get_arabic_month(month)
            return f"{month_name} {year}"
        except:
            return year_month
    
    def calculate_invoice(self, user_id: str, current_reading: float) -> Invoice:
        """حساب الفاتورة بناءً على القراءة"""
        today = datetime.datetime.now()
        year_month = today.strftime("%Y-%m")
        
        # الحصول على آخر قراءة
        last_reading = self.data_manager.get_last_reading(user_id)
        previous_reading = last_reading or 0
        
        # التحقق من صحة القراءة
        if current_reading < previous_reading:
            raise ValueError(f"القراءة الحالية ({current_reading}) أقل من السابقة ({previous_reading})")
        
        # الحسابات
        consumption = current_reading - previous_reading
        consumption_total = consumption * UNIT_PRICE
        total_bill = consumption_total + MONTHLY_FEE
        
        # اسم الشهر العربي
        month_name = self.get_arabic_month(today.month)
        arabic_date = f"{month_name} {today.year}"
        
        return Invoice(
            user_id=user_id,
            year_month=year_month,
            previous_reading=previous_reading,
            current_reading=current_reading,
            consumption=consumption,
            total_amount=total_bill,
            timestamp=today.strftime("%Y-%m-%d %H:%M:%S"),
            month_name=arabic_date
        )
    
    def format_invoice_message(self, invoice: Invoice, show_comparison: bool = True) -> str:
        """تنسيق رسالة الفاتورة بشكل جميل"""
        # الحسابات
        consumption_total = invoice.consumption * UNIT_PRICE
        
        # الرسالة الأساسية
        message = f"""
📋 *فاتورة المياه*
━━━━━━━━━━━━━━━━━━━━━━
📅 *الشهر:* {invoice.month_name}

🔢 *القراءة السابقة:* `{invoice.previous_reading:,.1f}`
🔢 *القراءة الحالية:* `{invoice.current_reading:,.1f}`
⚡ *الاستهلاك:* `{invoice.consumption:,.1f}` وحدة

💰 *تفاصيل الفاتورة:*
━━━━━━━━━━━━━━━━━━━━━━
• الاستهلاك: {invoice.consumption:,.1f} × {UNIT_PRICE:,} = {consumption_total:,.0f} {CURRENCY}
• الاشتراك الشهري: {MONTHLY_FEE:,} {CURRENCY}
━━━━━━━━━━━━━━━━━━━━━━
• *الإجمالي النهائي:* `{invoice.total_amount:,.0f}` {CURRENCY}

🕐 *تاريخ التسجيل:* {invoice.timestamp}
        """
        
        # إضافة مقارنة مع الشهر السابق
        if show_comparison:
            user_invoices = self.data_manager.get_user_invoices(invoice.user_id, limit=2)
            if len(user_invoices) > 1:
                prev_invoice = user_invoices[1]
                if prev_invoice["consumption"] > 0:
                    change = ((invoice.consumption - prev_invoice["consumption"]) / 
                             prev_invoice["consumption"]) * 100
                    
                    if change > 0:
                        trend = f"📈 زيادة بنسبة {abs(change):.1f}%"
                    elif change < 0:
                        trend = f"📉 انخفاض بنسبة {abs(change):.1f}%"
                    else:
                        trend = "⏸️ بدون تغيير"
                    
                    message += f"\n📊 *المقارنة:* {trend} عن الشهر الماضي"
        
        return message.strip()
    
    def create_main_keyboard(self) -> InlineKeyboardMarkup:
        """إنشاء الكيبورد الرئيسي"""
        keyboard = [
            [
                InlineKeyboardButton("📝 قراءة جديدة", callback_data="new_reading"),
                InlineKeyboardButton("📊 فواتير سابقة", callback_data="view_history")
            ],
            [
                InlineKeyboardButton("📈 إحصائياتي", callback_data="my_stats"),
                InlineKeyboardButton("⏰ التذكيرات", callback_data="reminder_settings")
            ],
            [
                InlineKeyboardButton("🔄 نسخة احتياطية", callback_data="backup_data"),
                InlineKeyboardButton("ℹ️ المساعدة", callback_data="help")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def create_history_keyboard(self, user_id: str) -> InlineKeyboardMarkup:
        """إنشاء كيبورد لسجل الفواتير"""
        invoices = self.data_manager.get_user_invoices(user_id, limit=6)
        keyboard = []
        
        for invoice in invoices:
            month_display = self.get_arabic_date_from_ym(invoice["year_month"])
            button_text = f"📅 {month_display} - {invoice['total_amount']:,} {CURRENCY}"
            keyboard.append([
                InlineKeyboardButton(
                    button_text, 
                    callback_data=f"invoice_detail_{invoice['year_month']}"
                )
            ])
        
        # أزرار التحكم
        if len(invoices) > 6:
            keyboard.append([
                InlineKeyboardButton("📋 المزيد من الفواتير", callback_data="more_invoices")
            ])
        
        keyboard.append([
            InlineKeyboardButton("📤 تصدير البيانات", callback_data="export_data"),
            InlineKeyboardButton("🔙 الرئيسية", callback_data="back_to_main")
        ])
        
        return InlineKeyboardMarkup(keyboard)
    
    def create_settings_keyboard(self, user_id: str) -> InlineKeyboardMarkup:
        """إنشاء كيبورد الإعدادات"""
        user_data = self.data_manager.get_user(user_id)
        reminder_status = "✅ مفعل" if user_data.get("reminder_enabled", True) else "❌ معطل"
        
        keyboard = [
            [
                InlineKeyboardButton(f"⏰ التذكيرات: {reminder_status}", 
                                   callback_data="toggle_reminder")
            ],
            [
                InlineKeyboardButton(" بياناتي", callback_data="my_profile"),
                InlineKeyboardButton("📱 جهات اتصال", callback_data="emergency_contacts")
            ],
            [
                InlineKeyboardButton("🔙 الرئيسية", callback_data="back_to_main")
            ]
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    # ============ معالجات الأوامر ============
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /start"""
        user = update.effective_user
        user_id = str(user.id)
        
        # تحديث بيانات المستخدم
        self.data_manager.update_user(user_id, {
            "first_name": user.first_name or "",
            "username": user.username or "",
            "last_active": datetime.datetime.now().isoformat()
        })
        
        # الرسالة الترحيبية
        welcome_message = f"""
مرحباً *{user.first_name}*! 👋

*بوت فاتورة المياه المتكامل*
أهلاً بك في نظام إدارة فواتير المياه الذكي.

*✨ المميزات المتاحة:*
📝 تسجيل قراءات شهرية تلقائية
📊 سجل كامل للفواتير السابقة
📈 إحصائيات وتقارير مفصلة
⏰ تذكيرات ذكية قابلة للتخصيص
💾 نسخ احتياطية تلقائية
📤 تصدير البيانات بسهولة

*📱 اختر من القائمة أدناه لبدء الاستخدام:*
        """
        
        await update.message.reply_text(
            welcome_message,
            reply_markup=self.create_main_keyboard(),
            parse_mode="Markdown"
        )
    
    async def handle_reading(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالجة إرسال قراءة جديدة"""
        user_id = str(update.message.from_user.id)
        text = update.message.text.strip()
        
        # إظهار حالة الكتابة
        await update.message.chat.send_action(action="typing")
        
        # إظهار حالة الكتابة
        await update.message.chat.send_action(action="typing")
        
        try:
            # التحقق من أن النص رقم
            try:
                current_reading = float(text)
            except ValueError:
                keyboard = [[InlineKeyboardButton("🔙 المحاولة مرة أخرى", callback_data="new_reading")]]
                await update.message.reply_text(
                    "❌ *خطأ في الإدخال*\n"
                    "يرجى إرسال رقم صحيح فقط.\n"
                    "مثال: `145` أو `156.5`",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return
            
            # حساب وحفظ الفاتورة
            invoice = self.calculate_invoice(user_id, current_reading)
            invoice_id = self.data_manager.save_invoice(invoice)
            
            # إرسال الفاتورة
            invoice_message = self.format_invoice_message(invoice)
            
            keyboard = [
                [InlineKeyboardButton("💾 حفظ الفاتورة", callback_data=f"save_invoice_{invoice_id}")],
                [InlineKeyboardButton("📤 مشاركة الفاتورة", callback_data=f"share_invoice_{invoice_id}")],
                [
                    InlineKeyboardButton("📝 قراءة جديدة", callback_data="new_reading"),
                    InlineKeyboardButton("📊 الفواتير", callback_data="view_history")
                ]
            ]
            
            await update.message.reply_text(
                invoice_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            
            # إشعار النجاح
            success_message = f"""
✅ *تم حفظ القراءة بنجاح!*

• الرقم المرجعي: `{invoice_id}`
• تم التسجيل: {invoice.timestamp}
• يمكنك استرجاع هذه الفاتورة لاحقاً
            """
            
            await update.message.reply_text(
                success_message,
                parse_mode="Markdown"
            )
            
        except ValueError as e:
            error_msg = str(e)
            if "أقل من" in error_msg:
                keyboard = [[InlineKeyboardButton("🔙 تصحيح القراءة", callback_data="new_reading")]]
                await update.message.reply_text(
                    f"⚠️ *تنبيه:* {error_msg}\n\n"
                    "يرجى التحقق من الرقم وإعادة الإرسال.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    "❌ *حدث خطأ غير متوقع*\n"
                    "يرجى المحاولة مرة أخرى.",
                    parse_mode="Markdown"
                )
        
        except Exception as e:
            logger.error(f"خطأ في معالجة القراءة: {e}")
            await update.message.reply_text(
                "❌ *حدث خطأ في الخادم*\n"
                "يرجى المحاولة لاحقاً.",
                parse_mode="Markdown"
            )
    
    async def invoice_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /invoice"""
        user_id = str(update.message.from_user.id)
        
        if not context.args:
            # عرض سجل الفواتير
            await self.show_user_history(update, context)
            return
        
        # استرجاع فاتورة شهر معين
        year_month = context.args[0]
        
        try:
            # التحقق من صيغة التاريخ
            datetime.datetime.strptime(year_month, "%Y-%m")
        except ValueError:
            await update.message.reply_text(
                "❌ *صيغة تاريخ غير صحيحة*\n"
                "استخدم الصيغة: `YYYY-MM`\n"
                "*مثال:* `/invoice 2024-01`",
                parse_mode="Markdown"
            )
            return
        
        invoice = self.data_manager.get_invoice_by_month(user_id, year_month)
        
        if invoice:
            # تحويل إلى كائن Invoice لعرضه
            invoice_obj = Invoice(**invoice)
            invoice_message = self.format_invoice_message(invoice_obj, show_comparison=False)
            
            keyboard = [
                [InlineKeyboardButton("📊 جميع الفواتير", callback_data="view_history")],
                [InlineKeyboardButton("🔙 الرئيسية", callback_data="back_to_main")]
            ]
            
            await update.message.reply_text(
                invoice_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"📭 *لا توجد فاتورة لشهر {year_month}*\n"
                "استخدم `/history` لعرض الفواتير المتاحة.",
                parse_mode="Markdown"
            )
    
    async def history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /history"""
        await self.show_user_history(update, context)
    
    async def show_user_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض سجل فواتير المستخدم"""
        user_id = str(update.effective_user.id)
        invoices = self.data_manager.get_user_invoices(user_id)
        
        if not invoices:
            keyboard = [[InlineKeyboardButton("📝 سجل قراءة جديدة", callback_data="new_reading")]]
            await update.message.reply_text(
                "📭 *لا توجد فواتير سابقة*\n"
                "ابدأ بتسجيل أول قراءة لك.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return
        
        # إعداد رسالة السجل
        stats = self.data_manager.get_user_stats(user_id)
        
        history_message = f"""
📊 *سجل الفواتير الشخصي*
━━━━━━━━━━━━━━━━━━━━━━

*📈 الإحصائيات:*
• عدد الفواتير: `{stats['total_invoices']}`
• إجمالي الاستهلاك: `{stats['total_consumption']:,.1f}` وحدة
• إجمالي المدفوعات: `{stats['total_amount']:,.0f}` {CURRENCY}
• متوسط شهري: `{stats['avg_consumption']:,.1f}` وحدة

*📅 آخر {min(5, len(invoices))} فواتير:*
        """
        
        for i, invoice in enumerate(invoices[:5], 1):
            month_display = self.get_arabic_date_from_ym(invoice["year_month"])
            history_message += f"\n{i}. *{month_display}* - {invoice['consumption']:,.1f} وحدة - {invoice['total_amount']:,.0f} {CURRENCY}"
        
        if len(invoices) > 5:
            history_message += f"\n\n... و {len(invoices) - 5} فاتورة أخرى"
        
        # إرسال الرسالة مع الكيبورد
        reply_markup = self.create_history_keyboard(user_id)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                history_message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                history_message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /stats"""
        user_id = str(update.effective_user.id)
        
        stats = self.data_manager.get_user_stats(user_id)
        
        if stats["total_invoices"] == 0:
            msg = "📭 *لا توجد بيانات كافية*\nسجل بعض القراءات أولاً للحصول على إحصائيات."
            if update.callback_query:
                await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
            else:
                await update.message.reply_text(msg, parse_mode="Markdown")
            return
        
        # حساب أكثر وأقل الشهور استهلاكاً
        invoices = self.data_manager.get_user_invoices(user_id, limit=100)
        
        if invoices:
            max_invoice = max(invoices, key=lambda x: x["consumption"])
            min_invoice = min(invoices, key=lambda x: x["consumption"])
            
            max_month = self.get_arabic_date_from_ym(max_invoice["year_month"])
            min_month = self.get_arabic_date_from_ym(min_invoice["year_month"])
        else:
            max_month = min_month = "لا توجد بيانات"
        
        stats_message = f"""
📈 *التقرير الإحصائي الشخصي*
━━━━━━━━━━━━━━━━━━━━━━

*📊 الإحصائيات العامة:*
• عدد الفواتير: `{stats['total_invoices']}`
• إجمالي الاستهلاك: `{stats['total_consumption']:,.1f}` وحدة
• إجمالي المدفوعات: `{stats['total_amount']:,.0f}` {CURRENCY}
• متوسط شهري: `{stats['avg_consumption']:,.1f}` وحدة

*🏆 الأرقام القياسية:*
• أعلى استهلاك: `{max_invoice['consumption']:,.1f}` وحدة ({max_month})
• أقل استهلاك: `{min_invoice['consumption']:,.1f}` وحدة ({min_month})

*📅 الفترة الزمنية:*
• أول فاتورة: {stats['first_invoice'] or 'غير متوفر'}
• آخر فاتورة: {stats['last_invoice'] or 'غير متوفر'}

*💰 التكلفة الشهرية المتوقعة:*
`{stats['avg_consumption'] * UNIT_PRICE + MONTHLY_FEE:,.0f}` {CURRENCY}
        """
        
        keyboard = [
            [InlineKeyboardButton("📊 الفواتير التفصيلية", callback_data="view_history")],
            [InlineKeyboardButton("📤 تصدير التقرير", callback_data="export_stats")],
            [InlineKeyboardButton("🔙 الرئيسية", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await update.callback_query.edit_message_text(stats_message, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(stats_message, reply_markup=reply_markup, parse_mode="Markdown")
    
    async def remind_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /remind"""
        user_id = str(update.effective_user.id)
        
        if not context.args:
            # عرض حالة التذكير الحالية
            user_data = self.data_manager.get_user(user_id)
            status = "✅ مفعل" if user_data.get("reminder_enabled", True) else "❌ معطل"
            time = user_data.get("notification_time", "10:00")
            
            await update.message.reply_text(
                f"⏰ *إعدادات التذكيرات*\n\n"
                f"• الحالة: {status}\n"
                f"• الموعد: يوم {REMINDER_DAY} الساعة {REMINDER_HOUR}:{REMINDER_MINUTE}\n\n"
                f"استخدم:\n"
                f"`/remind on` لتشغيل التذكيرات\n"
                f"`/remind off` لإيقاف التذكيرات",
                parse_mode="Markdown"
            )
            return
        
        action = context.args[0].lower()
        user_data = self.data_manager.get_user(user_id)
        
        if action in ["on", "تشغيل", "تفعيل", "نعم"]:
            user_data["reminder_enabled"] = True
            self.data_manager.update_user(user_id, {"reminder_enabled": True})
            
            await update.message.reply_text(
                "✅ *تم تشغيل التذكيرات الشهرية*\n"
                "سيتم تذكيرك يوم 25 من كل الشهر.",
                parse_mode="Markdown"
            )
        
        elif action in ["off", "إيقاف", "تعطيل", "لا"]:
            user_data["reminder_enabled"] = False
            self.data_manager.update_user(user_id, {"reminder_enabled": False})
            
            await update.message.reply_text(
                "❌ *تم إيقاف التذكيرات الشهرية*",
                parse_mode="Markdown"
            )
        
    
    async def backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /backup"""
        # هذا الأمر للمطور فقط
        user_id = str(update.effective_user.id)
        
        # هنا يمكنك إضافة تحقق من صلاحيات المطور
        # if user_id != "YOUR_USER_ID":
        #     await update.message.reply_text("⛔ غير مصرح لك بهذا الأمر.")
        #     return
        
        await update.message.reply_text(
            "🔄 *جاري إنشاء نسخة احتياطية...*",
            parse_mode="Markdown"
        )
        
        backup_file = self.data_manager.create_backup("manual")
        
        if backup_file:
            await update.message.reply_text(
                f"✅ *تم إنشاء نسخة احتياطية بنجاح*\n"
                f"الملف: `{os.path.basename(backup_file)}`\n"
                f"الحجم: {os.path.getsize(backup_file) // 1024} كيلوبايت",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "❌ *فشل إنشاء نسخة احتياطية*",
                parse_mode="Markdown"
            )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج أمر /help"""
        help_text = """
*🆘 مركز المساعدة - بوت فاتورة المياه*

*🔧 الأوامر المتاحة:*
━━━━━━━━━━━━━━━━━━━━━━
📝 *إرسال قراءة:* أرسل رقم قراءة العداد فقط
📋 `/invoice [YYYY-MM]` - فاتورة شهر معين
📊 `/history` - سجل الفواتير
📈 `/stats` - إحصائيات شخصية
⏰ `/remind [on/off/time]` - إدارة التذكيرات
🔄 `/backup` - نسخة احتياطية (للمطور)
ℹ️ `/help` - هذه الرسالة

*🎮 الأزرار التفاعلية:*
━━━━━━━━━━━━━━━━━━━━━━
• 📝 قراءة جديدة - تسجيل قراءة الشهر الحالي
• 📊 فواتير سابقة - عرض وتصفح الفواتير
• 📈 إحصائياتي - تقرير مفصل عن الاستهلاك
• ⏰ التذكيرات - إعدادات التذكيرات الشهرية
• 💾 نسخة احتياطية - حفظ نسخة من بياناتك
• ℹ️ المساعدة - تعليمات الاستخدام

*💡 نصائح سريعة:*
━━━━━━━━━━━━━━━━━━━━━━
• يمكنك إرسال قراءة العدار كرقم فقط
• الفواتير تحفظ تلقائياً ولا يمكن حذفها
• التذكيرات ترسل يوم 25 من كل شهر
• البيانات تحفظ محلياً في ملف JSON
• يمكنك تصدير بياناتك في أي وقت

*📞 للدعم الفني:*
لأي استفسارات تقنية، يرجى التواصل مع المطور.
        """
        
        keyboard = [[InlineKeyboardButton("🔙 الرئيسية", callback_data="back_to_main")]]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await update.callback_query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")
    
    # ============ معالج الأزرار ============
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالجة ضغطات الأزرار"""
        query = update.callback_query
        await query.answer()
        
        user_id = str(query.from_user.id)
        data = query.data
        
        # مسح الحالة عند ضغط أي زر
        if "state" in context.user_data:
            del context.user_data["state"]
        
        if data == "new_reading":
            await query.edit_message_text(
                "📝 *تسجيل قراءة جديدة*\n\n"
                "أرسل قراءة العداد الحالية كرقم فقط:\n"
                "*مثال:* `145` أو `156.5`\n\n"
                "📌 سيتم حساب الفاتورة تلقائياً.",
                parse_mode="Markdown"
            )
        
        elif data == "view_history":
            await self.show_user_history(update, context)
        
        elif data == "my_stats":
            await self.stats_command(update, context)
        
        elif data == "reminder_settings":
            await self.show_reminder_settings(update, context)
        
        elif data == "backup_data":
            await self.handle_backup_request(update, context)
        
        elif data == "help":
            await self.help_command(update, context)
        
        elif data == "back_to_main":
            await query.edit_message_text(
                "🏠 *القائمة الرئيسية*\n\n"
                "اختر من الخيارات أدناه:",
                reply_markup=self.create_main_keyboard(),
                parse_mode="Markdown"
            )
        
        elif data == "toggle_reminder":
            await self.toggle_reminder(update, context)
        
        elif data.startswith("invoice_detail_"):
            year_month = data.replace("invoice_detail_", "")
            await self.show_invoice_detail(update, context, year_month)
        
        elif data.startswith("save_invoice_"):
            invoice_id = data.replace("save_invoice_", "")
            await self.save_invoice_action(update, context, invoice_id)
        
        elif data == "more_invoices":
            await self.show_all_invoices(update, context)
        
        elif data == "export_data":
            await self.export_user_data(update, context)
        
        elif data == "export_stats":
            await self.export_stats_action(update, context)
        
        elif data == "my_profile":
            await self.show_user_profile(update, context)
        
        elif data == "emergency_contacts":
            await self.show_emergency_contacts(update, context)

    
    async def show_reminder_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض إعدادات التذكير"""
        user_id = str(update.effective_user.id)
        reply_markup = self.create_settings_keyboard(user_id)
        
        await update.callback_query.edit_message_text(
            "⚙️ *إعدادات التذكيرات*\n\n"
            "يمكنك تعديل إعدادات التذكيرات الشهرية من هنا:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    async def toggle_reminder(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تبديل حالة التذكيرات"""
        user_id = str(update.effective_user.id)
        user_data = self.data_manager.get_user(user_id)
        
        current_status = user_data.get("reminder_enabled", True)
        new_status = not current_status
        
        self.data_manager.update_user(user_id, {"reminder_enabled": new_status})
        
        status_text = "✅ مفعل" if new_status else "❌ معطل"
        message_text = f"✅ تم {'تشغيل' if new_status else 'إيقاف'} التذكيرات"
        
        await update.callback_query.edit_message_text(
            f"⚙️ *إعدادات التذكيرات*\n\n"
            f"• الحالة: {status_text}\n\n"
            f"{message_text}",
            reply_markup=self.create_settings_keyboard(user_id),
            parse_mode="Markdown"
        )
    
    async def show_invoice_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE, year_month: str):
        """عرض تفاصيل فاتورة معينة"""
        user_id = str(update.effective_user.id)
        invoice = self.data_manager.get_invoice_by_month(user_id, year_month)
        
        if invoice:
            invoice_obj = Invoice(**invoice)
            invoice_message = self.format_invoice_message(invoice_obj, show_comparison=False)
            
            keyboard = [
                [InlineKeyboardButton("📊 العودة للفواتير", callback_data="view_history")],
                [InlineKeyboardButton("🔙 الرئيسية", callback_data="back_to_main")]
            ]
            
            await update.callback_query.edit_message_text(
                invoice_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
    
    async def save_invoice_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE, invoice_id: str):
        """معالجة حفظ الفاتورة"""
        await update.callback_query.edit_message_text(
            "✅ *تم حفظ الفاتورة*\n\n"
            "يمكنك استرجاعها في أي وقت من سجل الفواتير.",
            parse_mode="Markdown"
        )
    
    async def show_all_invoices(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض جميع الفواتير"""
        user_id = str(update.effective_user.id)
        invoices = self.data_manager.get_user_invoices(user_id, limit=50)
        
        if not invoices:
            await update.callback_query.edit_message_text(
                "📭 *لا توجد فواتير*",
                parse_mode="Markdown"
            )
            return
        
        message = "📋 *جميع الفواتير*\n\n"
        
        for i, invoice in enumerate(invoices, 1):
            month_display = self.get_arabic_date_from_ym(invoice["year_month"])
            message += f"{i}. *{month_display}* - {invoice['consumption']:,.1f} وحدة - {invoice['total_amount']:,.0f} {CURRENCY}\n"
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="view_history")]]
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    async def export_user_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تصدير بيانات المستخدم"""
        user_id = str(update.effective_user.id)
        invoices = self.data_manager.get_user_invoices(user_id)
        
        if not invoices:
            await update.callback_query.edit_message_text(
                "📭 *لا توجد بيانات للتصدير*",
                parse_mode="Markdown"
            )
            return
        
        # إنشاء بيانات التصدير
        export_data = {
            "user_id": user_id,
            "export_date": datetime.datetime.now().isoformat(),
            "total_invoices": len(invoices),
            "invoices": invoices
        }
        
        # حفظ كملف JSON مؤقت
        export_file = f"export_{user_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            with open(export_file, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            # هنا يمكنك إرسال الملف للمستخدم
            # await context.bot.send_document(chat_id=user_id, document=open(export_file, 'rb'))
            
            # حذف الملف المؤقت
            os.remove(export_file)
            
            await update.callback_query.edit_message_text(
                "📤 *تم تصدير البيانات*\n\n"
                "سيتم إرسال ملف البيانات لك قريباً.\n"
                "⚠️ هذه الميزة قيد التطوير.",
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"خطأ في التصدير: {e}")
            await update.callback_query.edit_message_text(
                "❌ *فشل تصدير البيانات*",
                parse_mode="Markdown"
            )
    
    async def export_stats_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تصدير الإحصائيات"""
        await update.callback_query.edit_message_text(
            "📈 *تصدير التقرير الإحصائي*\n\n"
            "سيتم إرسال تقرير مفصل بكافة إحصائياتك.\n"
            "⚠️ هذه الميزة قيد التطوير.",
            parse_mode="Markdown"
        )
    
    async def handle_backup_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالجة طلب نسخة احتياطية"""
        await update.callback_query.edit_message_text(
            "💾 *النسخ الاحتياطي*\n\n"
            "يتم إنشاء نسخ احتياطية تلقائية يومياً.\n"
            "لإنشاء نسخة يدوية، استخدم الأمر:\n"
            "`/backup`\n\n"
            "⚠️ هذه الميزة للمطورين فقط.",
            parse_mode="Markdown"
        )
    
    async def show_user_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض ملف المستخدم"""
        user_id = str(update.effective_user.id)
        user_data = self.data_manager.get_user(user_id)
        stats = self.data_manager.get_user_stats(user_id)
        
        profile_message = f"""
👤 *الملف الشخصي*
━━━━━━━━━━━━━━━━━━━━━━

*🆔 المعلومات:*
• رقم المستخدم: `{user_id}`
• الاسم: {user_data.get('first_name', 'غير محدد')}
• اسم المستخدم: @{user_data.get('username', 'غير محدد')}
• تاريخ التسجيل: {user_data.get('created_at', 'غير معروف')}

*📊 الإحصائيات:*
• عدد الفواتير: {stats['total_invoices']}
• إجمالي الاستهلاك: {stats['total_consumption']:,.1f} وحدة
• إجمالي المدفوعات: {stats['total_amount']:,.0f} {CURRENCY}

*⏰ الإعدادات:*
• التذكيرات: {'✅ مفعل' if user_data.get('reminder_enabled', True) else '❌ معطل'}
• وقت التذكير: {user_data.get('notification_time', '10:00')}
• آخر نشاط: {user_data.get('last_active', 'غير معروف')}
        """
        
        keyboard = [
            [InlineKeyboardButton("⚙️ تعديل الإعدادات", callback_data="reminder_settings")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="reminder_settings")]
        ]
        
        await update.callback_query.edit_message_text(
            profile_message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    async def show_emergency_contacts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض جهات الاتصال للطوارئ"""
        contacts_message = """
📞 *جهات الاتصال للطوارئ*
━━━━━━━━━━━━━━━━━━━━━━

*💧 شركة المياه:*
• الهاتف: `9200 1234`
• الطوارئ: `933`
• الشكاوى: `940`

*🔧 الصيانة:*
• صيانة العدادات: `9200 5678`
• بلاغات التسرب: `955`

*📧 التواصل:*
• البريد الإلكتروني: support@water-company.com
• الموقع: www.water-company.com

*⏰ أوقات العمل:*
• الأحد - الخميس: 8 صباحاً - 4 مساءً
• الجمعة والسبت: إجازة
        """
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="reminder_settings")]]
        
        await update.callback_query.edit_message_text(
            contacts_message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    # ============ نظام التذكيرات ============
    
    def setup_scheduler(self):
        """إعداد المهام المجدولة"""
        # تذكير يوم 25 من كل شهر
        self.scheduler.add_job(
            self.send_monthly_reminders,
            CronTrigger(day=REMINDER_DAY, hour=REMINDER_HOUR, minute=REMINDER_MINUTE),
            id='monthly_reminder',
            name='إرسال التذكيرات الشهرية'
        )

        # تذكير ثاني يوم 25 (قبل نهاية الشهر)
        self.scheduler.add_job(
            self.send_mid_month_reminders,
            CronTrigger(day=SECOND_REMINDER_DAY, hour=REMINDER_HOUR, minute=REMINDER_MINUTE),
            id='mid_month_reminder',
            name='تذكير الاستعداد لنهاية الشهر'
        )
        
        # نسخ احتياطي يومي في منتصف الليل
        self.scheduler.add_job(
            self.data_manager.create_auto_backup,
            CronTrigger(hour=0, minute=5),
            id='daily_backup',
            name='النسخ الاحتياطي اليومي'
        )
        
        # تنظيف النسخ القديمة أسبوعياً
        self.scheduler.add_job(
            self.data_manager.cleanup_old_backups,
            CronTrigger(day_of_week='sun', hour=1, minute=0),
            id='cleanup_backups',
            name='تنظيف النسخ القديمة'
        )
        
        self.scheduler.start()
        logger.info("تم بدء نظام المهام المجدولة")
    
    async def send_monthly_reminders(self):
        """إرسال تذكير شهري لجميع المستخدمين"""
        if not hasattr(self, 'app'):
            return
        
        today = datetime.datetime.now()
        # حساب الشهر السابق
        last_month_date = today.replace(day=1) - datetime.timedelta(days=1)
        arabic_month = self.get_arabic_month(last_month_date.month)
        reminder_year = last_month_date.year
        
        users = self.data_manager.get_all_users_for_reminder()
        
        reminder_count = 0
        failed_count = 0
        
        for user_id, user_data in users:
            try:
                # كيبورد التذكير
                keyboard = [[InlineKeyboardButton("📝 سجل القراءة الآن", callback_data="new_reading")]]
                
                reminder_message = f"""
⏰ *تذكير بتسجيل قراءة العداد*
━━━━━━━━━━━━━━━━━━━━━━

السلام عليكم {user_data.get('first_name', '')}،

يرجى تسجيل قراءة عداد المياه لشهر *{arabic_month} {reminder_year}*.

📅 *موعد التسجيل:* يوم 25 من كل شهر
💰 *لتجنب الغرامات:* سجل القراءة في الوقت المحدد

أرسل قراءة العداد الحالية كرسالة نصية.

شكراً لتعاونكم! 💧
                """
                
                await self.app.bot.send_message(
                    chat_id=user_id,
                    text=reminder_message,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                reminder_count += 1
                logger.info(f"تم إرسال تذكير للمستخدم {user_id}")
                
            except Exception as e:
                failed_count += 1
                logger.error(f"فشل إرسال تذكير للمستخدم {user_id}: {e}")
        
        logger.info(f"تم إرسال {reminder_count} تذكير، فشل {failed_count}")

    async def send_mid_month_reminders(self):
        """إرسال تذكير في منتصف/أواخر الشهر"""
        if not hasattr(self, 'app'):
            return
            
        today = datetime.datetime.now()
        arabic_month = self.get_arabic_month(today.month)
        
        users = self.data_manager.get_all_users_for_reminder()
        
        for user_id, user_data in users:
            try:
                msg = f"""
⏰ *تذكير إضافي*
━━━━━━━━━━━━━━━━━━━━━━
أهلاً {user_data.get('first_name', '')}،

نقترب من نهاية شهر *{arabic_month}*.
يرجى الاستعداد لتسجيل قراءة العداد في يوم 1 القادم.

شكراً لتعاونكم! 💧
"""
                await self.app.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"فشل إرسال تذكير منتصف الشهر للمستخدم {user_id}: {e}")
    
    # ============ تشغيل البوت ============
    
    async def send_startup_notification(self, application: Application):
        """إرسال إشعار عند بدء التشغيل"""
        users = self.data_manager.get_all_users_for_reminder()
        count = 0
        
        print(f"DEBUG: Found {len(users)} users for notification.")
        
        for user_id, user_data in users:
            try:
                print(f"DEBUG: Sending notification to {user_id}")
                await application.bot.send_message(
                    chat_id=user_id,
                    text="🤖 *تنبيه النظام*\n\n"
                         "تم إعادة تشغيل البوت بنجاح وهو جاهز للعمل الآن.\n"
                         "شكراً لصبركم! 💧",
                    parse_mode="Markdown"
                )
                count += 1
            except Exception as e:
                logger.error(f"فشل إرسال إشعار البدء للمستخدم {user_id}: {e}")
                print(f"DEBUG: Failed to send to {user_id}: {e}")
        
        logger.info(f"تم إرسال إشعار البدء إلى {count} مستخدم")
        print(f"DEBUG: Sent {count} notifications.")

    async def post_init(self, application: Application):
        """تهيئة ما بعد التشغيل"""
        self.app = application
        self.setup_scheduler()
        # إرسال إشعار العودة للعمل (يمكن تعليقه إذا كان مزعجاً)
        await self.send_startup_notification(application)

    async def force_reminders_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إرسال التذكيرات فوراً لجميع المستخدمين"""
        user_id = str(update.effective_user.id)
        
        # رسالة تأكيد البدء
        await update.message.reply_text("⏳ *جاري إرسال التذكيرات للجميع...*", parse_mode="Markdown")
        
        try:
            # الحصول على جميع المستخدمين (شامل المعطلين للتذكير)
            users = list(self.data_manager.data.get("users", {}).items())
            
            today = datetime.datetime.now()
            # حساب الشهر السابق
            last_month_date = today.replace(day=1) - datetime.timedelta(days=1)
            arabic_month = self.get_arabic_month(last_month_date.month)
            reminder_year = last_month_date.year
            
            success_count = 0
            failed_count = 0
            
            for user_id, user_data in users:
                try:
                    # تفطي المستخدمين الذين ليس لديهم chat_id صالح (إذا كان user_id هو الـ chat_id)
                    try:
                        chat_id = int(user_id)
                    except ValueError:
                        continue

                    # كيبورد التذكير
                    keyboard = [[InlineKeyboardButton("📝 سجل القراءة الآن", callback_data="new_reading")]]
                    
                    reminder_message = f"""
⏰ *تذكير بتسجيل قراءة العداد*
━━━━━━━━━━━━━━━━━━━━━━

السلام عليكم {user_data.get('first_name', '')}،

يرجى تسجيل قراءة عداد المياه لشهر *{arabic_month} {reminder_year}*.

📅 *تذكير إداري:* يرجى تسجيل القراءة في أقرب وقت.

أرسل قراءة العداد الحالية كرسالة نصية.

شكراً لتعاونكم! 💧
                    """
                    
                    await self.app.bot.send_message(
                        chat_id=chat_id,
                        text=reminder_message,
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
                    success_count += 1
                    # تأخير بسيط لتجنب الحظر
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    failed_count += 1
                    logger.error(f"فشل إرسال التذكير للمستخدم {user_id}: {e}")
            
            await update.message.reply_text(
                f"✅ *تم الانتهاء من الإرسال*\n\n"
                f"• تم الإرسال بنجاح: `{success_count}`\n"
                f"• فشل الإرسال: `{failed_count}`",
                parse_mode="Markdown"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")

    def run(self):
        """تشغيل البوت"""
        # بناء التطبيق
        self.app = Application.builder().token(self.token).post_init(self.post_init).build()
        
        # إضافة المعالجات
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("invoice", self.invoice_command))
        self.app.add_handler(CommandHandler("history", self.history_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("remind", self.remind_command))
        self.app.add_handler(CommandHandler("force_reminders", self.force_reminders_command))
        self.app.add_handler(CommandHandler("backup", self.backup_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        
        # معالج الأزرار
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        
        # معالج الرسائل (القراءات)
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_reading
        ))
        
        # بدء البوت
        print("=" * 50)
        print("Water Bill Bot - Full Version")
        print("=" * 50)
        # print(f"Bot Link: https://t.me/{self.app.bot.username}") # تم التعليق لتجنب خطأ التهيئة
        print(f"Data File: {DATA_FILE}")
        print(f"Backups: {BACKUP_DIR}")
        print(f"Reminders: Day {REMINDER_DAY} at {REMINDER_HOUR}:{REMINDER_MINUTE}")
        print("=" * 50)
        print("Bot is running...")
        print("Press Ctrl+C to stop")
        
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

# ============ تشغيل البرنامج ============
if __name__ == "__main__":
    # التحقق من وجود التوكن
    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("Error: Token not found")
        print("Please check .env file for BOT_TOKEN")
        exit(1)
    
    # إنشاء مجلد النسخ الاحتياطية إذا لم يكن موجوداً
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        print(f"Created backup directory: {BACKUP_DIR}")
    
    # تشغيل البوت
    try:
        bot = WaterBillBot(TOKEN)
        bot.run()
    except KeyboardInterrupt:
        print("\nBot stopped")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"Error: {e}")