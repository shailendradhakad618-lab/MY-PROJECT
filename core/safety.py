import re
RISKY=("delete","remove","format","shutdown","restart","send","purchase","pay","transfer","uninstall","close all")
def is_risky(text):
    s=str(text).lower(); return any(re.search(r'\b'+re.escape(x)+r'\b',s) for x in RISKY)
def allowed_action(tool): return tool not in {"delete_files","format_disk","send_message_unconfirmed","transfer_money"}
