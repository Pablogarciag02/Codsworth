import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, timedelta
import hashlib
import streamlit_cookies_manager as scm

# ============================================
# CONFIGURATION
# ============================================

# Your Google Sheet URL
SHEET_URL = "https://docs.google.com/spreadsheets/d/1VWRloXPN1MtTpjMzusCNQfuHTGLWsg9XfI1zhjw4mwo/edit?gid=1334141231#gid=1334141231"

# Authentication (salted SHA-256)
SALT = st.secrets["auth"]["SALT"]
PASSWORD_HASH = st.secrets["auth"]["PASSWORD_HASH"]

# ============================================
# SESSION MANAGEMENT
# ============================================

# Initialize cookie manager
cookies = scm.EncryptedCookieManager(
    prefix="finance_tracker_",
    password="finance_tracker_cookie_key_2025_pablo"
)

if not cookies.ready():
    st.stop()

def set_auth_cookie():
    """Set authentication cookie that expires in 30 days"""
    expiry = (datetime.now() + timedelta(days=30)).isoformat()
    cookies['auth_expiry'] = expiry
    cookies.save()

def check_auth_cookie():
    """Check if authentication cookie is still valid"""
    if 'auth_expiry' in cookies:
        expiry = datetime.fromisoformat(cookies['auth_expiry'])
        if datetime.now() < expiry:
            return True
    return False

def clear_auth_cookie():
    """Remove authentication cookie"""
    if 'auth_expiry' in cookies:
        del cookies['auth_expiry']
        cookies.save()

# ============================================
# AUTHENTICATION
# ============================================

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = check_auth_cookie()

if not st.session_state.authenticated:
    st.title('💰 Finance Tracker')
    st.markdown('### Login')
    
    password = st.text_input('Password', type='password', key='login_password')
    remember_me = st.checkbox('Remember me for 30 days', value=True)
    
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button('Login'):
            salted_password = password + SALT
            hashed_attempt = hashlib.sha256(salted_password.encode()).hexdigest()
            
            if hashed_attempt == PASSWORD_HASH:
                st.session_state.authenticated = True
                if remember_me:
                    set_auth_cookie()
                st.rerun()
            else:
                st.error('❌ Incorrect password')
    
    st.stop()

# User is authenticated - show main app
st.title('💰 Finance Tracker')
st.sidebar.success('✅ Logged in')

if st.sidebar.button('Logout'):
    st.session_state.authenticated = False
    clear_auth_cookie()
    st.rerun()

# ============================================
# CONNECT TO GOOGLE SHEETS
# ============================================

@st.cache_resource
def get_google_sheet():
    """Connect to Google Sheets using service account"""
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    # Load credentials from Streamlit secrets
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes
    )
    
    client = gspread.authorize(creds)
    sheet = client.open_by_url(SHEET_URL)
    return sheet

try:
    sheet = get_google_sheet()
    st.sidebar.success('✅ Connected to Google Sheets')
except Exception as e:
    st.error(f'Failed to connect to Google Sheets: {e}')
    st.stop()

# ============================================
# BALANCE UPDATE FUNCTIONS
# ============================================

def update_sub_category_balance(parent_category, sub_category, amount):
    """Update balance for a specific sub-category"""
    sub_sheet = sheet.worksheet('Sub_Category_Balances')
    data = sub_sheet.get_all_records()
    
    # Find the row
    for idx, row in enumerate(data, start=2):  # Start at 2 (row 1 is header)
        if row['Parent_Category'] == parent_category and row['Sub_Category'] == sub_category:
            current_balance = row['Current_Balance']
            
            # Convert to float if string
            if isinstance(current_balance, str):
                current_balance = float(current_balance.replace(',', ''))
            
            new_balance = current_balance + amount
            
            # Update the cell (column D is Current_Balance)
            sub_sheet.update_cell(idx, 4, new_balance)
            return new_balance
    
    raise ValueError(f"Sub-category not found: {parent_category} -> {sub_category}")

def update_category_balance(category, amount):
    """Update balance for a category (non-Entretenimiento)"""
    cat_sheet = sheet.worksheet('Category_Balance')
    data = cat_sheet.get_all_records()
    
    # Find the row
    for idx, row in enumerate(data, start=2):  # Start at 2 (row 1 is header)
        if row['Category'] == category:
            current_balance = row['Current_Balance']
            
            # Convert to float if string
            if isinstance(current_balance, str):
                current_balance = float(current_balance.replace(',', ''))
            
            new_balance = current_balance + amount
            
            # Update the cell (column C is Current_Balance)
            cat_sheet.update_cell(idx, 3, new_balance)
            return new_balance
    
    raise ValueError(f"Category not found: {category}")

def update_pago_tdc(amount):
    """Update Pago_TDC (credit card debt)"""
    return update_category_balance('Pago_TDC', amount)

def distribute_income(total_amount):
    """Distribute income across all categories by percentage"""
    cat_sheet = sheet.worksheet('Category_Balance')
    data = cat_sheet.get_all_records()
    
    sub_sheet = sheet.worksheet('Sub_Category_Balances')
    sub_data = sub_sheet.get_all_records()
    
    updates = []
    
    # First pass: update categories
    for idx, row in enumerate(data, start=2):
        category = row['Category']
        percentage = row.get('Percentage', 0)
        
        # Skip special rows and categories with 0%
        if category in ['Pago_TDC', 'Pago_SAT', 'Tengo', 'Total_NU'] or not percentage:
            continue
        
        # Convert percentage to float if it's a string
        if isinstance(percentage, str):
            percentage = float(percentage.strip('%').replace(',', '')) / 100 if '%' in percentage else float(percentage)
        
        # Calculate allocation
        allocation = total_amount * percentage
        current_balance = row['Current_Balance']
        
        # Convert current_balance to float if needed
        if isinstance(current_balance, str):
            current_balance = float(current_balance.replace(',', ''))
        
        new_balance = current_balance + allocation
        
        # For Entretenimiento, we'll update sub-categories instead
        if category != 'Entretenimiento':
            cat_sheet.update_cell(idx, 3, new_balance)
            updates.append(f"{category}: +${allocation:,.2f}")
    
    # Second pass: update Entretenimiento sub-categories
    entretenimiento_allocation = total_amount * 0.14  # 14% for Entretenimiento
    
    for idx, row in enumerate(sub_data, start=2):
        if row['Parent_Category'] == 'Entretenimiento':
            sub_percentage = row['Percentage']
            
            # Convert percentage to float if it's a string
            if isinstance(sub_percentage, str):
                sub_percentage = float(sub_percentage.strip('%').replace(',', '')) / 100 if '%' in sub_percentage else float(sub_percentage)
            
            sub_allocation = entretenimiento_allocation * sub_percentage
            current_balance = row['Current_Balance']
            
            # Convert current_balance to float if needed
            if isinstance(current_balance, str):
                current_balance = float(current_balance.replace(',', ''))
            
            new_balance = current_balance + sub_allocation
            
            sub_sheet.update_cell(idx, 4, new_balance)
            updates.append(f"  └─ {row['Sub_Category']}: +${sub_allocation:,.2f}")
    
    return updates

def process_transaction(amount, description, type_tx, category, sub_category, is_credit):
    """Process transaction and update balances accordingly"""
    updates = []
    
    if type_tx == "Expense":
        # Update category/sub-category balance
        if sub_category:
            new_balance = update_sub_category_balance(category, sub_category, -amount)
            updates.append(f"{category} → {sub_category}: ${new_balance:,.2f}")
        else:
            new_balance = update_category_balance(category, -amount)
            updates.append(f"{category}: ${new_balance:,.2f}")
        
        # If credit, increase Pago_TDC
        if is_credit:
            new_debt = update_pago_tdc(amount)
            updates.append(f"Pago_TDC: ${new_debt:,.2f}")
    
    elif type_tx == "Income":
        # Distribute across all categories
        updates = distribute_income(amount)
    
    elif type_tx == "PAGO_TDC":
        # Reduce Pago_TDC
        new_debt = update_pago_tdc(-amount)
        updates.append(f"Pago_TDC: ${new_debt:,.2f}")
    
    elif type_tx == "Rembolso":
        # Add back to category/sub-category
        if sub_category:
            new_balance = update_sub_category_balance(category, sub_category, amount)
            updates.append(f"{category} → {sub_category}: ${new_balance:,.2f}")
        else:
            new_balance = update_category_balance(category, amount)
            updates.append(f"{category}: ${new_balance:,.2f}")
    
    return updates

# ============================================
# DASHBOARD
# ============================================

st.header('📊 Dashboard')

# Read Category_Balance sheet
category_balance_sheet = sheet.worksheet('Category_Balance')
category_data = category_balance_sheet.get_all_records()

# Display key metrics
col1, col2, col3 = st.columns(3)

# Find specific values
total_nu = next((item['Current_Balance'] for item in category_data if item['Category'] == 'Total_NU'), 0)
pago_tdc = next((item['Current_Balance'] for item in category_data if item['Category'] == 'Pago_TDC'), 0)
tengo = next((item['Current_Balance'] for item in category_data if item['Category'] == 'Tengo'), 0)

with col1:
    st.metric('Total en NU', f'${total_nu:,.2f}')
with col2:
    st.metric('Debo (TDC)', f'${pago_tdc:,.2f}')
with col3:
    st.metric('Tengo Real', f'${tengo:,.2f}')

# Category balances
st.subheader('Category Balances')

# Filter out special rows
categories_to_show = [item for item in category_data 
                      if item['Category'] not in ['Pago_TDC', 'Pago_SAT', 'Tengo', 'Total_NU']]

for cat in categories_to_show:
    percentage = cat.get('Percentage', 0)
    balance = cat.get('Current_Balance', 0)
    
    # Show percentage if it exists
    if percentage:
        st.metric(f"{cat['Category']} ({percentage*100:.0f}%)", f"${balance:,.2f}")
    else:
        st.metric(cat['Category'], f"${balance:,.2f}")

# Entretenimiento sub-categories
st.subheader('Entretenimiento Breakdown')
sub_balance_sheet = sheet.worksheet('Sub_Category_Balances')
sub_data = sub_balance_sheet.get_all_records()

col1, col2 = st.columns(2)
with col1:
    gf_time = next((item['Current_Balance'] for item in sub_data if item['Sub_Category'] == 'GF Time'), 0)
    st.metric('└─ GF Time', f'${gf_time:,.2f}')
with col2:
    social = next((item['Current_Balance'] for item in sub_data if item['Sub_Category'] == 'Social/Food/Friends'), 0)
    st.metric('└─ Social/Food/Friends', f'${social:,.2f}')

# ============================================
# TRANSACTION FORM
# ============================================

st.header('📝 Log Transaction')

# Type selector OUTSIDE the form - changing it triggers full script reload
type_tx = st.selectbox('Type', ['Expense', 'Income', 'PAGO_TDC', 'Rembolso'], key='type_selector')

# Now the form renders based on current type_tx value (after script reload)
with st.form('transaction_form'):
    amount = st.number_input('Amount (MXN)', min_value=0.0, step=0.01)
    description = st.text_input('Description', placeholder='e.g., kebab 2x1 mario')
    
    category_options = ['Retiro', 'Emergencia', 'House Fund', 'Crecimiento', 'Desarrollo Personal', 
                      'Entretenimiento', 'Viajes', 'Gastos Futuros', 'Necesidades Básicas']
    
    if type_tx in ['Expense', 'Rembolso']:
        category = st.selectbox('Category', category_options)
        
        sub_category_options = ['No sub-category', 'GF Time', 'Social/Food/Friends']
        sub_category_selected = st.selectbox('Sub-Category', sub_category_options)
        sub_category = '' if sub_category_selected == 'No sub-category' else sub_category_selected
        
        if type_tx == 'Expense':
            is_credit = st.checkbox('Paid with credit card?')
        else:
            is_credit = False
    else:
        # Income or PAGO_TDC - don't render category/subcategory fields at all
        category = ''
        sub_category = ''
        is_credit = False
    
    submitted = st.form_submit_button('Log Transaction')
    
    if submitted:
        if amount <= 0:
            st.error('Amount must be greater than 0')
        elif type_tx in ['Expense', 'Rembolso'] and category == 'Entretenimiento' and not sub_category:
            st.error('❌ Entretenimiento requires a sub-category (GF Time or Social/Food/Friends)')
        elif type_tx in ['Expense', 'Rembolso'] and category != 'Entretenimiento' and sub_category:
            st.error(f'❌ {category} does not use sub-categories. Please select "No sub-category"')
        else:
            try:
                transactions_sheet = sheet.worksheet('Transactions')
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                transactions_sheet.append_row([
                    timestamp,
                    amount,
                    description,
                    type_tx,
                    category,
                    sub_category,
                    is_credit
                ])
                
                updates = process_transaction(amount, description, type_tx, category, sub_category, is_credit)
                
                st.success(f'✅ Transaction logged: ${amount:,.2f} - {description}')
                
                with st.expander("Balance Updates", expanded=True):
                    for update in updates:
                        st.text(update)
                
                st.rerun()
                
            except Exception as e:
                st.error(f'Error processing transaction: {e}')
                import traceback
                st.error(traceback.format_exc())