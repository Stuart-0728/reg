#!/bin/bash
# Remove old reminder cron and add new
(crontab -l | grep -v 'send_reminders.py') | crontab -
(crontab -l 2>/dev/null; echo "0 12 * * * /var/www/reg/current/venv/bin/python /var/www/reg/current/scripts/send_reminders.py >> /var/www/reg/current/logs/cron.log 2>&1") | crontab -
