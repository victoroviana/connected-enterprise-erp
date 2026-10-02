import json, re

total = 0
with_org = 0
with_contacts = 0
no_org_examples = []

with open('data/rd_station/rd_crm_deals.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        total += 1
        d = json.loads(line)
        org = d.get('organization')
        cts = d.get('contacts')
        if org and (org.get('id') or org.get('_id')):
            with_org += 1
        else:
            if len(no_org_examples) < 10:
                no_org_examples.append((d.get('name'), cts[0].get('name') if cts else None))
        if cts:
            with_contacts += 1

print(f"Total: {total}")
print(f"With Org: {with_org}")
print(f"With Contacts: {with_contacts}")
print("\nExamples without Org:")
for name, ct in no_org_examples:
    print(f"  Deal: {name} | Contact: {ct}")
