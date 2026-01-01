import sys
import os
sys.path.append(r"c:\Users\AL MASA\Desktop\TelgramBots\WaterBillBot")
from water3 import DataManager

def check_data():
    dm = DataManager()
    print(f"Data Loaded from: {dm.data_file}")
    users = dm.data.get("users", {})
    print(f"Total Users: {len(users)}")
    
    reminder_users = dm.get_all_users_for_reminder()
    print(f"Users with Reminder Enabled: {len(reminder_users)}")
    
    for user_id, data in users.items():
        print(f"User: {user_id}, Name: {data.get('first_name')}, Reminder: {data.get('reminder_enabled')}")

if __name__ == "__main__":
    check_data()
