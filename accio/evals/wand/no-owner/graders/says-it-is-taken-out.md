---
type: regex
target: last_message
pattern: '(taken|took|removed|dropped|cut|leaving|left)[^.\n]{0,40}Slack|Slack[\s\S]{0,160}\b(taken it out|took it out|removed|dropped|cut|no owner)\b'
flags: i
---
