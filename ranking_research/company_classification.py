"""Issuer model compatibility from explicit Codal document type.

Industry supplies operating peer groups, not a substitute for a holding-company
document type. Unknown templates never certify a general operating model.
"""
import re


def classify_template(title):
    text=re.sub(r'[^a-z]+',' ',str(title).casefold()).strip()
    if 'financial statement' not in text and 'financialstatement' not in text:return None
    if 'bank' in text:return 'bank'
    if 'insurance' in text:return 'insurance'
    if 'brokerage' in text or 'exchange' in text:return 'financial_services'
    if 'investment' in text:return 'investment'
    if 'building' in text or 'real estate' in text:return 'real_estate'
    operating=('general','product','production','manufacturing','service','industrial','agricultur','electric','cement','mining','trade')
    if any(word in text for word in operating):return 'general'
    return None


LABELS={'general':'شرکت عملیاتی','investment':'سرمایه‌گذاری / هلدینگ','bank':'بانک',
        'insurance':'بیمه','financial_services':'خدمات مالی','real_estate':'ساخت‌وساز / املاک','unknown':'نوع شرکت تأیید نشده'}
