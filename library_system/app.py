from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, has_request_context
import json
import os
import uuid
import csv
import io
import re
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
import pandas as pd
import plotly.graph_objects as go
import plotly.utils
import networkx as nx

app = Flask(__name__)
app.secret_key = 'library_secret_2024'

DATA_DIR = 'data'
BOOKS_FILE = os.path.join(DATA_DIR, 'books.json')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
BORROWS_FILE = os.path.join(DATA_DIR, 'borrows.json')
RESERVATIONS_FILE = os.path.join(DATA_DIR, 'reservations.json')
NOTIFICATIONS_FILE = os.path.join(DATA_DIR, 'notifications.json')

EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

@dataclass
class Book:
    id: str
    title: str
    author: str
    category: str = ''
    isbn: str = ''
    year: str = ''
    copies: int = 0
    copies_available: int = 0
    added_date: str = ''

    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data.get('id', ''),
            title=data.get('title', ''),
            author=data.get('author', ''),
            category=data.get('category', ''),
            isbn=data.get('isbn', ''),
            year=data.get('year', ''),
            copies=int(data.get('copies') or 0),
            copies_available=int(data.get('copies_available') or 0),
            added_date=data.get('added_date', '')
        )

    def to_dict(self):
        return asdict(self)

@dataclass
class User:
    id: str
    name: str
    email: str
    phone: str = ''
    member_type: str = 'Student'
    joined_date: str = ''

    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data.get('id', ''),
            name=data.get('name', ''),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            member_type=data.get('member_type', 'Student'),
            joined_date=data.get('joined_date', '')
        )

    def to_dict(self):
        return asdict(self)

@dataclass
class BorrowRecord:
    id: str
    book_id: str
    user_id: str
    borrow_date: str = ''
    due_date: str = ''
    returned: bool = False
    return_date: str = None

    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data.get('id', ''),
            book_id=data.get('book_id', ''),
            user_id=data.get('user_id', ''),
            borrow_date=data.get('borrow_date', ''),
            due_date=data.get('due_date', ''),
            returned=bool(data.get('returned', False)),
            return_date=data.get('return_date')
        )

    def to_dict(self):
        return asdict(self)

# ── Data Layer ──────────────────────────────────────────────────────────────

def load(path, default=None):
    if default is None:
        default = []
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        if has_request_context():
            flash(f'Error reading data from {os.path.basename(path)}: invalid JSON.', 'error')
        return default
    except Exception as exc:
        if has_request_context():
            flash(f'Unexpected error loading {os.path.basename(path)}.', 'error')
        return default

def save(path, data):
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    except Exception:
        if has_request_context():
            flash(f'Error saving {os.path.basename(path)}.', 'error')

def get_books():
    return load(BOOKS_FILE, [])

def get_users():
    return load(USERS_FILE, [])

def get_borrows():
    return load(BORROWS_FILE, [])

def get_reservations():
    return load(RESERVATIONS_FILE, {})

def save_books(d):
    save(BOOKS_FILE, d)

def save_users(d):
    save(USERS_FILE, d)

def save_borrows(d):
    save(BORROWS_FILE, d)

def save_reservations(d):
    save(RESERVATIONS_FILE, d)

# ── Binary Search ────────────────────────────────────────────────────────────

def binary_search_books(books, query, field):
    """Binary search on sorted list; falls back to linear for partial match."""
    query = query.lower().strip()
    sorted_books = sorted(books, key=lambda b: b.get(field, '').lower())
    # Collect all partial matches efficiently
    results = []
    lo, hi = 0, len(sorted_books) - 1
    # Find leftmost start position
    start = len(sorted_books)
    while lo <= hi:
        mid = (lo + hi) // 2
        val = sorted_books[mid].get(field, '').lower()
        if val.startswith(query):
            start = mid
            hi = mid - 1
        elif val < query:
            lo = mid + 1
        else:
            hi = mid - 1
    # Collect all matches forward from start
    i = start
    while i < len(sorted_books) and sorted_books[i].get(field, '').lower().startswith(query):
        results.append(sorted_books[i])
        i += 1
    # Augment with substring matches not caught by prefix
    ids_found = {b['id'] for b in results}
    for b in books:
        if b['id'] not in ids_found and query in b.get(field, '').lower():
            results.append(b)
    return results

def search_books(query, field='title'):
    books = get_books()
    if not query:
        return books
    return binary_search_books(books, query, field)

# ── Recommendation Graph ─────────────────────────────────────────────────────

def build_recommendation_graph():
    borrows = get_borrows()
    books = {b['id']: b for b in get_books()}
    G = nx.Graph()
    for book in books.values():
        G.add_node(book['id'], **book)
    # Edge: same category
    cats = defaultdict(list)
    for b in books.values():
        cats[b.get('category', '')].append(b['id'])
    for ids in cats.values():
        for i in range(len(ids)):
            for j in range(i+1, len(ids)):
                if G.has_edge(ids[i], ids[j]):
                    G[ids[i]][ids[j]]['weight'] += 1
                else:
                    G.add_edge(ids[i], ids[j], weight=1)
    # Edge: co-borrowed by same user
    user_books = defaultdict(set)
    for br in borrows:
        user_books[br['user_id']].add(br['book_id'])
    for uid, bid_set in user_books.items():
        bid_list = list(bid_set)
        for i in range(len(bid_list)):
            for j in range(i+1, len(bid_list)):
                a, b_id = bid_list[i], bid_list[j]
                if a in G and b_id in G:
                    if G.has_edge(a, b_id):
                        G[a][b_id]['weight'] += 2
                    else:
                        G.add_edge(a, b_id, weight=2)
    return G, books

def recommend_for_user(user_id, top_n=6):
    G, books = build_recommendation_graph()
    borrows = get_borrows()
    borrowed_ids = {br['book_id'] for br in borrows if br['user_id'] == user_id}
    if not borrowed_ids:
        # Cold start: return most borrowed
        return get_most_borrowed_books(top_n)
    scores = defaultdict(float)
    for bid in borrowed_ids:
        if bid in G:
            for neighbor, data in G[bid].items():
                if neighbor not in borrowed_ids:
                    scores[neighbor] += data.get('weight', 1)
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    result = []
    for bid, score in ranked[:top_n]:
        if bid in books:
            b = dict(books[bid])
            b['score'] = round(score, 2)
            result.append(b)
    return result

def get_most_borrowed_books(n=6):
    borrows = get_borrows()
    books = {b['id']: b for b in get_books()}
    counts = defaultdict(int)
    for br in borrows:
        counts[br['book_id']] += 1
    ranked = sorted(counts.items(), key=lambda x: -x[1])[:n]
    result = []
    for bid, cnt in ranked:
        if bid in books:
            b = dict(books[bid])
            b['borrow_count'] = cnt
            result.append(b)
    return result

# ── Reservation Queue ─────────────────────────────────────────────────────────

def enqueue_reservation(book_id, user_id):
    res = get_reservations()
    if book_id not in res:
        res[book_id] = []
    if user_id not in res[book_id]:
        res[book_id].append(user_id)
        save_reservations(res)

def dequeue_reservation(book_id):
    res = get_reservations()
    if book_id in res and res[book_id]:
        user_id = res[book_id].pop(0)
        save_reservations(res)
        return user_id
    return None

def get_queue_position(book_id, user_id):
    res = get_reservations()
    q = res.get(book_id, [])
    try:
        return q.index(user_id) + 1
    except ValueError:
        return None

def sanitize_reservations():
    res = get_reservations()
    books = {b['id'] for b in get_books()}
    users = {u['id'] for u in get_users()}
    modified = False
    clean = {}
    for book_id, queue in res.items():
        if book_id not in books:
            modified = True
            continue
        safe_queue = []
        for user_id in queue:
            if user_id in users and user_id not in safe_queue:
                safe_queue.append(user_id)
            else:
                modified = True
        if safe_queue:
            clean[book_id] = safe_queue
    if modified:
        save_reservations(clean)
    return clean

def get_queue_statistics():
    """Return queue statistics based on the current reservations data."""
    reservations = sanitize_reservations()
    books_with_waiting = sum(1 for queue in reservations.values() if len(queue) > 0)
    people_waiting = sum(len(queue) for queue in reservations.values())
    return {
        'books_with_waiting_readers': books_with_waiting,
        'people_in_queue': people_waiting
    }

# ── Notification System ──────────────────────────────────────────────────────

def get_notifications():
    return load(NOTIFICATIONS_FILE, [])

def save_notifications(data):
    save(NOTIFICATIONS_FILE, data)

def create_notification(message, notification_type='info'):
    """Create and store a notification."""
    notifs = get_notifications()
    notif = {
        'message': message,
        'timestamp': datetime.now().isoformat(),
        'type': notification_type
    }
    notifs.append(notif)
    save_notifications(notifs)
    return notif

def get_recent_notifications(n=10):
    """Get latest n notifications (newest first)."""
    notifs = get_notifications()
    return sorted(notifs, key=lambda x: x.get('timestamp', ''), reverse=True)[:n]

# ── Demand Score System ──────────────────────────────────────────────────────

def get_demand_score(book_id):
    """Calculate demand score: borrow count + queue length."""
    borrows = get_borrows()
    res = sanitize_reservations()
    borrow_count = sum(1 for br in borrows if br['book_id'] == book_id)
    queue_length = len(res.get(book_id, []))
    return borrow_count + queue_length

def get_most_demanded_books(n=5):
    """Get top n books by demand score."""
    books = get_books()
    demand_list = []
    for book in books:
        score = get_demand_score(book['id'])
        demand_list.append((score, book['title'], book['id'], book))
    top = sorted(demand_list, key=lambda x: (-x[0], x[1]))[:n]
    return [{'book': item[3], 'demand_score': item[0]} for item in top]


# ── Reader Insights Helpers ─────────────────────────────────────────────────
def get_reader_statistics(user_id):
    """Return aggregated reader statistics from borrows and reservations."""
    borrows = get_borrows()
    books = {b['id']: b for b in get_books()}
    user_borrows = [b for b in borrows if b.get('user_id') == user_id]
    total_borrowed = len(user_borrows)
    active = [b for b in user_borrows if not b.get('returned')]
    returned = [b for b in user_borrows if b.get('returned')]
    overdue = []
    total_fines = 0
    for br in active:
        try:
            if datetime.fromisoformat(br.get('due_date')) < datetime.now():
                overdue.append(br)
        except Exception:
            pass
        f = calculate_fine(br)
        total_fines += f.get('amount', 0)

    # reservation membership count
    res = sanitize_reservations()
    queue_membership = sum(1 for q in res.values() if user_id in q)

    # recent history and reservation history
    recent_borrows = sorted(user_borrows, key=lambda x: x.get('borrow_date',''), reverse=True)[:10]
    reservations = []
    books_map = books
    for book_id, q in res.items():
        if user_id in q:
            reservations.append({
                'book_id': book_id,
                'book_title': books_map.get(book_id, {}).get('title', book_id),
                'position': q.index(user_id) + 1
            })

    return {
        'total_borrowed': total_borrowed,
        'active_borrows': len(active),
        'returned': len(returned),
        'overdue': len(overdue),
        'total_fines': total_fines,
        'queue_membership': queue_membership,
        'recent_borrows': recent_borrows,
        'reservation_history': reservations
    }


def get_favorite_category(user_id):
    """Return most common category the user borrows from."""
    borrows = get_borrows()
    books = {b['id']: b for b in get_books()}
    categories = defaultdict(int)
    for br in borrows:
        if br.get('user_id') != user_id:
            continue
        book = books.get(br.get('book_id'))
        if book:
            categories[book.get('category', 'Unknown')] += 1
    if not categories:
        return 'Unknown'
    return max(categories.items(), key=lambda x: x[1])[0]


def get_scarcity_alerts():
    """Generate scarcity alerts: out-of-stock, low-stock, high-demand, categories, recommendations."""
    books = get_books()
    borrows = get_borrows()
    res = sanitize_reservations()
    books_map = {b['id']: b for b in books}

    # compute queue lengths and demand scores
    out_of_stock = []
    low_stock = []
    demand_list = []
    for b in books:
        qlen = len(res.get(b['id'], []))
        score = get_demand_score(b['id'])
        entry = {
            'id': b['id'], 'title': b['title'], 'author': b.get('author',''),
            'copies_available': b.get('copies_available', 0), 'queue_length': qlen, 'demand_score': score,
            'category': b.get('category','')
        }
        if b.get('copies_available', 0) == 0:
            out_of_stock.append(entry)
        if b.get('copies_available', 0) <= 2:
            low_stock.append(entry)
        demand_list.append(entry)

    # high demand top 10
    high_demand = sorted(demand_list, key=lambda x: (-x['demand_score'], x['title']))[:10]

    # most requested categories
    cat_counts = defaultdict(int)
    for br in borrows:
        book = books_map.get(br.get('book_id'))
        if book:
            cat_counts[book.get('category','Unknown')] += 1
    most_requested_categories = sorted(cat_counts.items(), key=lambda x: -x[1])

    # recommended restocking: high demand and low availability
    recommended = [b for b in demand_list if b['demand_score'] >= 5 and b['copies_available'] <= 2]

    return {
        'out_of_stock': sorted(out_of_stock, key=lambda x: -x['demand_score']),
        'low_stock': sorted(low_stock, key=lambda x: (x['copies_available'], -x['demand_score'])),
        'high_demand': high_demand,
        'most_requested_categories': most_requested_categories,
        'recommended_restock': recommended
    }

# ── Fine Calculator ──────────────────────────────────────────────────────────

def calculate_fine(borrow_record):
    """Calculate fine: ₹20 per day overdue."""
    if borrow_record.get('returned'):
        return {'amount': 0, 'days_overdue': 0}
    try:
        due_date = datetime.fromisoformat(borrow_record['due_date'])
        current = datetime.now()
        if current > due_date:
            days_late = (current - due_date).days
            amount = max(0, days_late * 20)
            return {'amount': amount, 'days_overdue': days_late}
    except Exception:
        pass
    return {'amount': 0, 'days_overdue': 0}

def get_overdue_summary():
    """Get total overdue books and pending fines."""
    borrows = get_borrows()
    active = [br for br in borrows if not br.get('returned')]
    overdue_count = 0
    total_fine = 0
    for br in active:
        fine_info = calculate_fine(br)
        if fine_info['days_overdue'] > 0:
            overdue_count += 1
            total_fine += fine_info['amount']
    return {'overdue_count': overdue_count, 'total_fine': total_fine}

# ── Administration Helpers ───────────────────────────────────────────────────

def get_detailed_overdue_records():
    """Get detailed overdue records with user and book info."""
    borrows = get_borrows()
    books_map = {b['id']: b for b in get_books()}
    users_map = {u['id']: u for u in get_users()}
    
    overdue_records = []
    for br in borrows:
        if br.get('returned'):
            continue
        fine_info = calculate_fine(br)
        if fine_info['days_overdue'] > 0:
            book = books_map.get(br['book_id'], {})
            user = users_map.get(br['user_id'], {})
            overdue_records.append({
                'member': user.get('name', 'Unknown'),
                'book': book.get('title', 'Unknown'),
                'days_late': fine_info['days_overdue'],
                'fine': fine_info['amount'],
                'due_date': br.get('due_date', ''),
                'borrow_date': br.get('borrow_date', '')
            })
    return sorted(overdue_records, key=lambda x: -x['days_late'])

def build_circulation_log():
    """Build comprehensive circulation log from all records."""
    borrows = get_borrows()
    reservations_data = sanitize_reservations()
    books_map = {b['id']: b for b in get_books()}
    users_map = {u['id']: u for u in get_users()}
    
    log_entries = []
    
    # Add borrow events
    for br in borrows:
        book = books_map.get(br['book_id'], {})
        user = users_map.get(br['user_id'], {})
        log_entries.append({
            'timestamp': br.get('borrow_date', ''),
            'action': 'borrow',
            'member': user.get('name', 'Unknown'),
            'book': book.get('title', 'Unknown'),
            'details': f"{user.get('name', 'Unknown')} borrowed \"{book.get('title', 'Unknown')}\""
        })
        if br.get('returned'):
            log_entries.append({
                'timestamp': br.get('return_date', ''),
                'action': 'return',
                'member': user.get('name', 'Unknown'),
                'book': book.get('title', 'Unknown'),
                'details': f"{user.get('name', 'Unknown')} returned \"{book.get('title', 'Unknown')}\""
            })
    
    # Add queue allocation events (infer from current queue state + history)
    for book_id, queue in reservations_data.items():
        book = books_map.get(book_id, {})
        for i, user_id in enumerate(queue):
            user = users_map.get(user_id, {})
            log_entries.append({
                'timestamp': datetime.now().isoformat(),
                'action': 'queue',
                'member': user.get('name', 'Unknown'),
                'book': book.get('title', 'Unknown'),
                'details': f"{user.get('name', 'Unknown')} is position {i+1} in queue for \"{book.get('title', 'Unknown')}\""
            })
    
    # Sort by timestamp, newest first
    return sorted(log_entries, key=lambda x: x['timestamp'], reverse=True)

# ── Email & ISBN Validation ──────────────────────────────────────────────────

def email_exists(email, users, exclude_id=None):
    """Check if email already exists."""
    if not email:
        return False
    return any(u.get('email', '').lower() == email.lower() and u.get('id') != exclude_id for u in users)

def isbn_exists(isbn, books, exclude_id=None):
    if not isbn:
        return False
    return any(b.get('isbn') == isbn and b.get('id') != exclude_id for b in books)

# ── Enhanced Validation ──────────────────────────────────────────────────────

def validate_book_form(form, books, current_book_id=None):
    """Validate book form input."""
    title = form.get('title', '').strip()
    author = form.get('author', '').strip()
    copies = form.get('copies', '').strip()
    isbn = form.get('isbn', '').strip()
    
    if not title:
        return 'Book title cannot be empty.'
    if not author:
        return 'Author cannot be empty.'
    
    try:
        copies_val = int(copies)
        if copies_val < 0:
            return 'Number of copies cannot be negative.'
    except ValueError:
        return 'Copies must be a whole number.'
    
    if isbn and isbn_exists(isbn, books, exclude_id=current_book_id):
        return 'A book with this ISBN already exists.'
    
    return None

def validate_user_form(form, current_user_id=None):
    """Validate user form input."""
    name = form.get('name', '').strip()
    email = form.get('email', '').strip()
    users = get_users()
    
    if not name:
        return 'User name cannot be empty.'
    if not email or not EMAIL_PATTERN.match(email):
        return 'Please provide a valid email address.'
    if email_exists(email, users, exclude_id=current_user_id):
        return 'A user with this email already exists.'
    
    return None

def find_book_by_id(book_id):
    return next((b for b in get_books() if b['id'] == book_id), None)

def find_user_by_id(user_id):
    return next((u for u in get_users() if u['id'] == user_id), None)

# ── Analytics ────────────────────────────────────────────────────────────────

def analytics_most_borrowed():
    try:
        borrows = get_borrows()
        books = {b['id']: b['title'] for b in get_books()}
        df = pd.DataFrame(borrows)
        if df.empty or 'book_id' not in df.columns:
            raise ValueError('No borrow data available')
        counts = df['book_id'].value_counts().head(10)
        labels = [books.get(bid, bid)[:30] for bid in counts.index]
        values = counts.tolist()
        fig = go.Figure(go.Bar(
            x=values, y=labels, orientation='h',
            marker_color='#6C63FF',
            text=values, textposition='outside'
        ))
    except Exception:
        fig = go.Figure(go.Bar(x=[], y=[]))
    fig.update_layout(
        title='Top 10 Most Borrowed Books',
        xaxis_title='Borrow Count', yaxis_title='',
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'), height=380,
        margin=dict(l=10, r=30, t=50, b=30),
        yaxis=dict(autorange='reversed')
    )
    fig.update_layout(
        title='Top 10 Most Borrowed Books',
        xaxis_title='Borrow Count', yaxis_title='',
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'), height=380,
        margin=dict(l=10, r=30, t=50, b=30),
        yaxis=dict(autorange='reversed')
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

def analytics_category_popularity():
    try:
        borrows = get_borrows()
        books = get_books()
        df = pd.DataFrame(borrows)
        book_df = pd.DataFrame(books)
        if df.empty or 'book_id' not in df.columns or book_df.empty:
            raise ValueError('No data available')
        merged = df.merge(book_df[['id', 'category']], left_on='book_id', right_on='id', how='left')
        counts = merged['category'].fillna('Unknown').value_counts()
        labels = counts.index.tolist()
        values = counts.tolist()
        colors = ['#6C63FF','#FF6584','#43D9AD','#FFB347','#87CEEB','#DDA0DD','#98FB98','#F08080']
        fig = go.Figure(go.Pie(
            labels=labels, values=values,
            marker=dict(colors=colors[:len(labels)]),
            hole=0.45,
            textinfo='label+percent'
        ))
    except Exception:
        fig = go.Figure(go.Pie(labels=[], values=[]))
    fig.update_layout(
        title='Category Popularity',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'), height=360,
        margin=dict(l=10, r=10, t=50, b=10)
    )
    fig.update_layout(
        title='Category Popularity',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'), height=360,
        margin=dict(l=10, r=10, t=50, b=10)
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

def analytics_borrow_trend():
    try:
        borrows = get_borrows()
        df = pd.DataFrame(borrows)
        if df.empty or 'borrow_date' not in df.columns:
            raise ValueError('No borrow history')
        df['borrow_date'] = pd.to_datetime(df['borrow_date'], errors='coerce')
        counts = df.dropna(subset=['borrow_date']).groupby(df['borrow_date'].dt.date).size()
        x = counts.index.astype(str).tolist()
        y = counts.tolist()
        fig = go.Figure(go.Scatter(
            x=x, y=y, mode='lines+markers',
            line=dict(color='#43D9AD', width=2),
            marker=dict(color='#6C63FF', size=6),
            fill='tozeroy', fillcolor='rgba(67,217,173,0.1)'
        ))
    except Exception:
        fig = go.Figure(go.Scatter(x=[], y=[]))
    fig.update_layout(
        title='Borrow Activity Over Time',
        xaxis_title='Date', yaxis_title='Borrows',
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'), height=320,
        margin=dict(l=10, r=10, t=50, b=30)
    )
    fig.update_layout(
        title='Borrow Activity Over Time',
        xaxis_title='Date', yaxis_title='Borrows',
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'), height=320,
        margin=dict(l=10, r=10, t=50, b=30)
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

def analytics_active_users():
    try:
        borrows = get_borrows()
        users = get_users()
        df = pd.DataFrame(borrows)
        if df.empty or 'user_id' not in df.columns:
            raise ValueError('No borrow records')
        counts = df[~df.get('returned', False)].groupby('user_id').size().sort_values(ascending=False).head(8)
        user_map = {u['id']: u['name'] for u in users}
        labels = [user_map.get(uid, uid) for uid in counts.index]
        values = counts.tolist()
        fig = go.Figure(go.Bar(
            x=labels, y=values,
            marker_color=['#6C63FF','#FF6584','#43D9AD','#FFB347',
                          '#87CEEB','#DDA0DD','#98FB98','#F08080'][:len(labels)],
            text=values, textposition='outside'
        ))
    except Exception:
        fig = go.Figure(go.Bar(x=[], y=[]))
    fig.update_layout(
        title='Most Active Users',
        xaxis_title='User', yaxis_title='Total Borrows',
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'), height=340,
        margin=dict(l=10, r=10, t=50, b=60)
    )
    fig.update_layout(
        title='Most Active Users',
        xaxis_title='User', yaxis_title='Total Borrows',
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#e2e8f0'), height=340,
        margin=dict(l=10, r=10, t=50, b=60)
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

# ── Analytics: Additional Insights ──────────────────────────────────────────

def analytics_top_borrowed():
    """Generate top borrowed books analytics."""
    try:
        borrows = get_borrows()
        books = {b['id']: b['title'] for b in get_books()}
        df = pd.DataFrame(borrows)
        if df.empty or 'book_id' not in df.columns:
            raise ValueError('No data')
        counts = df['book_id'].value_counts().head(8)
        labels = [books.get(bid, bid)[:25] for bid in counts.index]
        values = counts.tolist()
        fig = go.Figure(go.Bar(
            x=values, y=labels, orientation='h',
            marker_color='#C9A227',
            text=values, textposition='outside'
        ))
        fig.update_layout(
            title='Top Borrowed Books', xaxis_title='Times Borrowed', yaxis_title='',
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#e2e8f0'), height=340, yaxis=dict(autorange='reversed'),
            margin=dict(l=10, r=30, t=50, b=30)
        )
    except Exception:
        fig = go.Figure(go.Bar(x=[], y=[]))
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

def analytics_demand_score():
    """Generate most demanded books analytics."""
    try:
        demanded = get_most_demanded_books(8)
        if not demanded:
            raise ValueError('No data')
        labels = [item['book']['title'][:25] for item in demanded]
        values = [item['demand_score'] for item in demanded]
        fig = go.Figure(go.Bar(
            x=values, y=labels, orientation='h',
            marker_color='#8B6B3F',
            text=values, textposition='outside'
        ))
        fig.update_layout(
            title='Most Demanded Books', xaxis_title='Demand Score', yaxis_title='',
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#e2e8f0'), height=340, yaxis=dict(autorange='reversed'),
            margin=dict(l=10, r=30, t=50, b=30)
        )
    except Exception:
        fig = go.Figure(go.Bar(x=[], y=[]))
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

def analytics_borrow_duration():
    """Calculate average borrow duration."""
    try:
        borrows = get_borrows()
        df = pd.DataFrame(borrows)
        if df.empty or 'borrow_date' not in df.columns or 'return_date' not in df.columns:
            return 'N/A'
        df['borrow_date'] = pd.to_datetime(df['borrow_date'], errors='coerce')
        df['return_date'] = pd.to_datetime(df['return_date'], errors='coerce')
        duration = (df['return_date'] - df['borrow_date']).dt.days
        avg = duration.dropna()
        return f"{avg.mean():.1f} days" if not avg.empty else 'N/A'
    except Exception:
        return 'N/A'

# ── Routes: Dashboard ────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    books = get_books()
    users = get_users()
    borrows = get_borrows()
    active = [br for br in borrows if not br.get('returned')]
    overdue = [br for br in active
               if datetime.fromisoformat(br['due_date']) < datetime.now()]
    stats = {
        'total_books': len(books),
        'total_users': len(users),
        'active_borrows': len(active),
        'overdue': len(overdue),
        'total_copies': sum(b.get('copies', 0) for b in books),
        'available_copies': sum(b.get('copies_available', 0) for b in books),
    }
    recent_borrows = sorted(borrows, key=lambda x: x.get('borrow_date',''), reverse=True)[:5]
    users_map = {u['id']: u['name'] for u in users}
    books_map = {b['id']: b['title'] for b in books}
    for br in recent_borrows:
        br['user_name'] = users_map.get(br['user_id'], 'Unknown')
        br['book_title'] = books_map.get(br['book_id'], 'Unknown')
    
    # Quick insights
    most_borrowed_book = get_most_borrowed_books(1)
    most_active_user = None
    most_popular_category = 'N/A'
    if stats['active_borrows'] > 0:
        borrow_counts = defaultdict(int)
        for br in borrows:
            if not br.get('returned'):
                borrow_counts[br['user_id']] += 1
        if borrow_counts:
            top_user_id = max(borrow_counts.items(), key=lambda x: x[1])[0]
            most_active_user = next((u for u in users if u['id'] == top_user_id), None)
    
    try:
        book_df = pd.DataFrame(books)
        if not book_df.empty and 'category' in book_df.columns:
            categories = defaultdict(int)
            for br in borrows:
                book = next((b for b in books if b['id'] == br['book_id']), None)
                if book:
                    categories[book.get('category', 'Unknown')] += 1
            if categories:
                most_popular_category = max(categories.items(), key=lambda x: x[1])[0]
    except Exception:
        pass
    # Today's priorities
    try:
        today = datetime.now().date()
        due_today_count = 0
        for br in active:
            try:
                if datetime.fromisoformat(br.get('due_date')).date() == today:
                    due_today_count += 1
            except Exception:
                pass
    except Exception:
        due_today_count = 0

    overdue_count = len(overdue)

    # Demand threshold configurable via query param (fallback 5)
    try:
        demand_threshold = int(request.args.get('demand_threshold', 5))
    except Exception:
        demand_threshold = 5

    high_demand_count = 0
    low_stock_count = 0
    try:
        for b in books:
            score = get_demand_score(b['id'])
            if score > demand_threshold:
                high_demand_count += 1
            if b.get('copies_available', 0) <= 2:
                low_stock_count += 1
    except Exception:
        high_demand_count = 0
        low_stock_count = 0

    priorities = {
        'due_today': due_today_count,
        'overdue': overdue_count,
        'high_demand': high_demand_count,
        'low_stock': low_stock_count,
        'demand_threshold': demand_threshold
    }
    queue_status = get_queue_statistics()
    
    return render_template('dashboard.html', 
                         stats=stats, 
                         recent_borrows=recent_borrows,
                         most_borrowed=most_borrowed_book[0] if most_borrowed_book else None,
                         most_active_user=most_active_user,
                         most_popular_category=most_popular_category,
                         priorities=priorities,
                         queue_status=queue_status)

# ── Routes: Books ─────────────────────────────────────────────────────────────

@app.route('/books')
def books_list():
    query = request.args.get('q', '')
    field = request.args.get('field', 'title')
    books = search_books(query, field)
    return render_template('books.html', books=books, query=query, field=field)


# ── Routes: Reader Profiles & Scarcity Alerts ─────────────────────────────────

@app.route('/reader_profiles')
def reader_profiles():
    q = request.args.get('q','').strip().lower()
    users = get_users()
    enriched = []
    for u in users:
        uid = u['id']
        stats = get_reader_statistics(uid)
        fav = get_favorite_category(uid)
        try:
            recs = recommend_for_user(uid)
            rec_count = len(recs)
        except Exception:
            rec_count = 0
        summary = {
            'id': uid,
            'name': u.get('name','Unknown'),
            'email': u.get('email',''),
            'member_type': u.get('member_type',''),
            'total_borrowed': stats['total_borrowed'],
            'active_borrows': stats['active_borrows'],
            'favorite_category': fav,
            'recommendations_count': rec_count
        }
        # apply search filter if present
        if q:
            if q in summary['name'].lower() or q in summary['email'].lower() or q in summary['member_type'].lower():
                enriched.append(summary)
        else:
            enriched.append(summary)
    return render_template('reader_profiles.html', users=enriched)


@app.route('/reader_profiles/<user_id>')
def reader_profile(user_id):
    users = get_users()
    user = next((u for u in users if u['id'] == user_id), None)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('reader_profiles'))
    stats = get_reader_statistics(user_id)
    favorite = get_favorite_category(user_id)
    return render_template('reader_profile.html', user=user, stats=stats, favorite=favorite)


@app.route('/scarcity_alerts')
def scarcity_alerts():
    alerts = get_scarcity_alerts()
    return render_template('scarcity_alerts.html', alerts=alerts)

@app.route('/books/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        books = get_books()
        error = validate_book_form(request.form, books)
        if error:
            flash(error, 'error')
            return redirect(url_for('add_book'))
        copies = int(request.form.get('copies', 1))
        book = {
            'id': str(uuid.uuid4())[:8],
            'title': request.form['title'].strip(),
            'author': request.form['author'].strip(),
            'category': request.form.get('category', '').strip(),
            'isbn': request.form.get('isbn', '').strip(),
            'year': request.form.get('year', '').strip(),
            'copies': copies,
            'copies_available': copies,
            'added_date': datetime.now().isoformat()
        }
        books.append(book)
        save_books(books)
        create_notification(f'New book added: "{book["title"]}" by {book["author"]}', 'info')
        flash('Book added successfully!', 'success')
        return redirect(url_for('books_list'))
    return render_template('book_form.html', book=None)

@app.route('/books/edit/<book_id>', methods=['GET', 'POST'])
def edit_book(book_id):
    books = get_books()
    book = next((b for b in books if b['id'] == book_id), None)
    if not book:
        flash('Book not found.', 'error')
        return redirect(url_for('books_list'))
    if request.method == 'POST':
        error = validate_book_form(request.form, books, current_book_id=book_id)
        if error:
            flash(error, 'error')
            return redirect(url_for('edit_book', book_id=book_id))
        old_copies = book['copies']
        book['title'] = request.form['title'].strip()
        book['author'] = request.form['author'].strip()
        book['category'] = request.form.get('category', '').strip()
        book['isbn'] = request.form.get('isbn', '').strip()
        book['year'] = request.form.get('year', '').strip()
        new_copies = int(request.form.get('copies', 1))
        diff = new_copies - old_copies
        book['copies'] = new_copies
        book['copies_available'] = max(0, book.get('copies_available', 0) + diff)
        save_books(books)
        flash('Book updated!', 'success')
        return redirect(url_for('books_list'))
    return render_template('book_form.html', book=book)

@app.route('/books/delete/<book_id>', methods=['POST'])
def delete_book(book_id):
    books = [b for b in get_books() if b['id'] != book_id]
    save_books(books)
    sanitize_reservations()
    flash('Book deleted.', 'info')
    return redirect(url_for('books_list'))

@app.route('/books/bulk_import', methods=['POST'])
def bulk_import_books():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400
    try:
        content = file.read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        books = get_books()
        added = 0
        errors = []
        for i, row in enumerate(reader, 1):
            try:
                copies = int(row.get('copies', 1))
                title = row.get('title', '').strip()
                author = row.get('author', '').strip()
                if not title or not author:
                    raise ValueError('Missing title or author')
                isbn = row.get('isbn', '').strip()
                if isbn and isbn_exists(isbn, books):
                    raise ValueError('Duplicate ISBN')
                book = {
                    'id': str(uuid.uuid4())[:8],
                    'title': title,
                    'author': author,
                    'category': row.get('category', 'General').strip(),
                    'isbn': isbn,
                    'year': row.get('year', '').strip(),
                    'copies': copies,
                    'copies_available': copies,
                    'added_date': datetime.now().isoformat()
                }
                books.append(book)
                added += 1
            except Exception as e:
                errors.append(f'Row {i}: {str(e)}')
        save_books(books)
        return jsonify({'added': added, 'errors': errors})
    except Exception:
        return jsonify({'error': 'Unable to process the uploaded book CSV file.'}), 400

# ── Routes: Users ─────────────────────────────────────────────────────────────

@app.route('/users')
def users_list():
    users = get_users()
    borrows = get_borrows()
    active_map = defaultdict(int)
    for br in borrows:
        if not br.get('returned'):
            active_map[br['user_id']] += 1
    for u in users:
        u['active_borrows'] = active_map.get(u['id'], 0)
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['GET', 'POST'])
def add_user():
    if request.method == 'POST':
        users = get_users()
        error = validate_user_form(request.form)
        if error:
            flash(error, 'error')
            return redirect(url_for('add_user'))
        user = {
            'id': str(uuid.uuid4())[:8],
            'name': request.form['name'].strip(),
            'email': request.form['email'].strip(),
            'phone': request.form.get('phone', '').strip(),
            'member_type': request.form.get('member_type', 'Student'),
            'joined_date': datetime.now().isoformat()
        }
        users.append(user)
        save_users(users)
        create_notification(f'New user registered: {user["name"]}', 'info')
        flash('User registered!', 'success')
        return redirect(url_for('users_list'))
    return render_template('user_form.html', user=None)

@app.route('/users/edit/<user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    users = get_users()
    user = next((u for u in users if u['id'] == user_id), None)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('users_list'))
    if request.method == 'POST':
        error = validate_user_form(request.form, current_user_id=user_id)
        if error:
            flash(error, 'error')
            return redirect(url_for('edit_user', user_id=user_id))
        user['name'] = request.form['name'].strip()
        user['email'] = request.form['email'].strip()
        user['phone'] = request.form.get('phone', '').strip()
        user['member_type'] = request.form.get('member_type', 'Student')
        save_users(users)
        flash('User updated!', 'success')
        return redirect(url_for('users_list'))
    return render_template('user_form.html', user=user)

@app.route('/users/delete/<user_id>', methods=['POST'])
def delete_user(user_id):
    users = [u for u in get_users() if u['id'] != user_id]
    save_users(users)
    sanitize_reservations()
    flash('User removed.', 'info')
    return redirect(url_for('users_list'))

@app.route('/users/bulk_import', methods=['POST'])
def bulk_import_users():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400
    try:
        content = file.read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        users = get_users()
        added = 0
        errors = []
        for i, row in enumerate(reader, 1):
            try:
                name = row.get('name', '').strip()
                email = row.get('email', '').strip()
                if not name:
                    raise ValueError('Missing user name')
                if not email or not EMAIL_PATTERN.match(email):
                    raise ValueError('Invalid email')
                user = {
                    'id': str(uuid.uuid4())[:8],
                    'name': name,
                    'email': email,
                    'phone': row.get('phone', '').strip(),
                    'member_type': row.get('member_type', 'Student').strip(),
                    'joined_date': datetime.now().isoformat()
                }
                users.append(user)
                added += 1
            except Exception as e:
                errors.append(f'Row {i}: {str(e)}')
        save_users(users)
        return jsonify({'added': added, 'errors': errors})
    except Exception:
        return jsonify({'error': 'Unable to process the uploaded user CSV file.'}), 400

# ── Routes: Borrow / Return ───────────────────────────────────────────────────

@app.route('/borrow', methods=['GET', 'POST'])
def borrow():
    books = get_books()
    users = get_users()
    if request.method == 'POST':
        book_id = request.form['book_id']
        user_id = request.form['user_id']
        days = int(request.form.get('days', 14))
        book = find_book_by_id(book_id)
        user = find_user_by_id(user_id)
        if not book:
            flash('Cannot borrow: selected book does not exist.', 'error')
            return redirect(url_for('borrow'))
        if not user:
            flash('Cannot borrow: selected user does not exist.', 'error')
            return redirect(url_for('borrow'))
        if book['copies_available'] <= 0:
            enqueue_reservation(book_id, user_id)
            pos = get_queue_position(book_id, user_id)
            create_notification(f'{user["name"]} joined queue for "{book["title"]}" (position {pos})', 'warning')
            flash(f'No copies available. Added to reservation queue (position {pos}).', 'warning')
            return redirect(url_for('borrow'))
        borrows = get_borrows()
        record = {
            'id': str(uuid.uuid4())[:8],
            'book_id': book_id,
            'user_id': user_id,
            'borrow_date': datetime.now().isoformat(),
            'due_date': (datetime.now() + timedelta(days=days)).isoformat(),
            'returned': False,
            'return_date': None
        }
        borrows.append(record)
        save_borrows(borrows)
        book['copies_available'] -= 1
        save_books(books)
        create_notification(f'{user["name"]} borrowed "{book["title"]}"', 'success')
        flash(f'Book borrowed! Due: {record["due_date"][:10]}', 'success')
        return redirect(url_for('borrow'))
    borrows = get_borrows()
    active = [br for br in borrows if not br.get('returned')]
    users_map = {u['id']: u['name'] for u in users}
    books_map = {b['id']: b for b in books}
    for br in active:
        br['user_name'] = users_map.get(br['user_id'], '')
        br['book_title'] = books_map.get(br['book_id'], {}).get('title', '')
        try:
            br['overdue'] = datetime.fromisoformat(br['due_date']) < datetime.now()
        except Exception:
            br['overdue'] = False
        br['fine'] = calculate_fine(br)
    return render_template('borrow.html', books=books, users=users, active_borrows=active)

@app.route('/return/<borrow_id>', methods=['POST'])
def return_book(borrow_id):
    borrows = get_borrows()
    books = get_books()
    br = next((b for b in borrows if b['id'] == borrow_id), None)
    if not br:
        flash('Record not found.', 'error')
        return redirect(url_for('borrow'))
    br['returned'] = True
    br['return_date'] = datetime.now().isoformat()
    save_borrows(borrows)
    book = find_book_by_id(br['book_id'])
    user = find_user_by_id(br['user_id'])
    if book and user:
        create_notification(f'{user["name"]} returned "{book["title"]}"', 'info')
    if book:
        book['copies_available'] = min(book['copies'], book['copies_available'] + 1)
        save_books(books)
    sanitized = sanitize_reservations()
    queue = sanitized.get(br['book_id'], [])
    next_user = queue[0] if queue else None
    if next_user:
        next_user_obj = find_user_by_id(next_user)
        if next_user_obj and book:
            create_notification(f'Book "{book["title"]}" allocated to {next_user_obj["name"]} from queue', 'success')
            flash(f"Notification: Book '{book['title']}' has been allocated to Student {next_user_obj['name']} from the waiting queue.", 'success')
        else:
            flash('Book returned and reservation queue updated.', 'success')
    else:
        flash('Book returned successfully!', 'success')
    return redirect(url_for('borrow'))

# ── API: Search Autocomplete ─────────────────────────────────────────────────

@app.route('/api/books/search', methods=['GET'])
def api_search_autocomplete():
    """Search autocomplete API for books."""
    query = request.args.get('q', '').strip().lower()
    if not query or len(query) < 2:
        return jsonify([])
    books = get_books()
    results = []
    for book in books:
        title_match = query in book.get('title', '').lower()
        author_match = query in book.get('author', '').lower()
        if title_match or author_match:
            results.append({
                'id': book['id'],
                'title': book['title'],
                'author': book['author'],
                'category': book.get('category', '')
            })
    return jsonify(results[:10])

# ── Routes: Reservations ──────────────────────────────────────────────────────

@app.route('/reservations')
def reservations():
    res = sanitize_reservations()
    queue_status = get_queue_statistics()
    books = {b['id']: b for b in get_books()}
    users = {u['id']: u for u in get_users()}
    data = []
    for book_id, queue in res.items():
        if queue:
            book = books.get(book_id, {})
            data.append({
                'book_id': book_id,
                'book_title': book.get('title', book_id),
                'queue': [{'pos': i+1, 'user_id': uid,
                           'user_name': users.get(uid, {}).get('name', uid)}
                          for i, uid in enumerate(queue)]
            })
    return render_template('reservations.html', reservations=data, queue_status=queue_status)

# ── Routes: Recommendations ───────────────────────────────────────────────────

@app.route('/recommendations')
def recommendations():
    users = get_users()
    user_id = request.args.get('user_id', '')
    recs = []
    selected_user_name = ''
    borrowed_count = 0
    if user_id:
        recs = recommend_for_user(user_id)
        user = next((u for u in users if u['id'] == user_id), None)
        selected_user_name = user['name'] if user else ''
        borrowed_count = sum(1 for br in get_borrows() if br['user_id'] == user_id)
    return render_template('recommendations.html', users=users,
                           selected_user=user_id, selected_user_name=selected_user_name,
                           borrowed_count=borrowed_count, recommendations=recs)

@app.route('/api/recommendations/<user_id>')
def api_recommendations(user_id):
    return jsonify(recommend_for_user(user_id))

# ── Routes: Analytics ─────────────────────────────────────────────────────────

@app.route('/analytics')
def analytics():
    borrows = get_borrows()
    books = get_books()
    users = get_users()
    total_active = 0
    popular_category = 'N/A'
    avg_duration = 'N/A'
    try:
        df = pd.DataFrame(borrows)
        book_df = pd.DataFrame(books)
        if not df.empty:
            total_active = int(df[~df.get('returned', False)].shape[0])
            if 'borrow_date' in df.columns and 'return_date' in df.columns:
                df['borrow_date'] = pd.to_datetime(df['borrow_date'], errors='coerce')
                df['return_date'] = pd.to_datetime(df['return_date'], errors='coerce')
                duration = (df['return_date'] - df['borrow_date']).dt.days
                avg = duration.dropna()
                avg_duration = f"{avg.mean():.1f} days" if not avg.empty else 'N/A'
            if not book_df.empty and 'id' in book_df.columns:
                merged = df.merge(book_df[['id', 'category']], left_on='book_id', right_on='id', how='left')
                popular_category = merged['category'].fillna('Unknown').mode().iloc[0] if 'category' in merged else 'N/A'
    except Exception:
        total_active = len([b for b in borrows if not b.get('returned')])
    demand_scores = []
    try:
        books_map = {b['id']: b for b in books}
        res = sanitize_reservations()
        borrow_counts = defaultdict(int)
        for br in borrows:
            borrow_counts[br['book_id']] += 1
        for book in books:
            bid = book['id']
            score = borrow_counts.get(bid, 0) + len(res.get(bid, []))
            demand_scores.append((score, book['title'], bid))
        top_trending = sorted(demand_scores, key=lambda x: (-x[0], x[1]))[:5]
    except Exception:
        top_trending = []
    stats = {
        'total_borrows': len(borrows),
        'active': total_active,
        'returned': len([b for b in borrows if b.get('returned')]),
        'overdue': len([b for b in borrows if not b.get('returned') and
                        datetime.fromisoformat(b['due_date']) < datetime.now()])
    }
    return render_template('analytics.html',
        chart_most_borrowed=analytics_most_borrowed(),
        chart_category=analytics_category_popularity(),
        chart_trend=analytics_borrow_trend(),
        chart_users=analytics_active_users(),
        stats=stats,
        total_books=len(books),
        total_users=len(users),
        popular_category=popular_category,
        average_duration=avg_duration,
        total_active_borrows=total_active,
        top_trending=top_trending,
        chart_demand=analytics_demand_score(),
        chart_top_borrowed=analytics_top_borrowed()
    )

# ── API: Search ────────────────────────────────────────────────────────────────

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '')
    field = request.args.get('field', 'title')
    return jsonify(search_books(q, field))

# ── Routes: Administration ─────────────────────────────────────────────────────

@app.route('/admin/notifications')
def admin_notifications():
    """Display all notifications with timeline view."""
    notifs = get_recent_notifications(100)
    return render_template('admin_notifications.html', notifications=notifs)

@app.route('/admin/overdue')
def admin_overdue():
    """Display overdue summary and detailed overdue records."""
    overdue_summary = get_overdue_summary()
    overdue_records = get_detailed_overdue_records()
    
    # Calculate average overdue duration
    avg_overdue = 0
    if overdue_records:
        avg_overdue = sum(r['days_late'] for r in overdue_records) / len(overdue_records)
    
    # Find most overdue member and book
    most_overdue_member = None
    most_overdue_book = None
    
    if overdue_records:
        member_counts = defaultdict(lambda: {'count': 0, 'total_fine': 0})
        book_counts = defaultdict(lambda: {'count': 0, 'total_fine': 0})
        
        for rec in overdue_records:
            member_counts[rec['member']]['count'] += 1
            member_counts[rec['member']]['total_fine'] += rec['fine']
            book_counts[rec['book']]['count'] += 1
            book_counts[rec['book']]['total_fine'] += rec['fine']
        
        if member_counts:
            most_overdue_member = max(member_counts.items(), 
                                      key=lambda x: x[1]['count'])[0]
        if book_counts:
            most_overdue_book = max(book_counts.items(), 
                                    key=lambda x: x[1]['count'])[0]
    
    return render_template('admin_overdue.html',
                         overdue_summary=overdue_summary,
                         overdue_records=overdue_records,
                         avg_overdue=round(avg_overdue, 1),
                         most_overdue_member=most_overdue_member,
                         most_overdue_book=most_overdue_book)

@app.route('/admin/circulation-log')
def admin_circulation_log():
    """Display comprehensive circulation log."""
    log_entries = build_circulation_log()
    return render_template('admin_circulation_log.html', log_entries=log_entries)

# ── Seed Data ──────────────────────────────────────────────────────────────────

def seed_data():
    if not get_books():
        sample_books = [
            {'id':'b001','title':'The Great Gatsby','author':'F. Scott Fitzgerald','category':'Fiction','isbn':'978-0743273565','year':'1925','copies':5,'copies_available':3},
            {'id':'b002','title':'To Kill a Mockingbird','author':'Harper Lee','category':'Fiction','isbn':'978-0061935466','year':'1960','copies':4,'copies_available':2},
            {'id':'b003','title':'Introduction to Algorithms','author':'Thomas H. Cormen','category':'Computer Science','isbn':'978-0262033848','year':'2009','copies':6,'copies_available':4},
            {'id':'b004','title':'Clean Code','author':'Robert C. Martin','category':'Computer Science','isbn':'978-0132350884','year':'2008','copies':3,'copies_available':1},
            {'id':'b005','title':'1984','author':'George Orwell','category':'Fiction','isbn':'978-0451524935','year':'1949','copies':5,'copies_available':5},
            {'id':'b006','title':'Sapiens','author':'Yuval Noah Harari','category':'History','isbn':'978-0062316097','year':'2011','copies':4,'copies_available':3},
            {'id':'b007','title':'The Pragmatic Programmer','author':'David Thomas','category':'Computer Science','isbn':'978-0135957059','year':'2019','copies':3,'copies_available':2},
            {'id':'b008','title':'Brave New World','author':'Aldous Huxley','category':'Fiction','isbn':'978-0060850524','year':'1932','copies':4,'copies_available':4},
            {'id':'b009','title':'A Brief History of Time','author':'Stephen Hawking','category':'Science','isbn':'978-0553380163','year':'1988','copies':3,'copies_available':2},
            {'id':'b010','title':'The Art of War','author':'Sun Tzu','category':'Philosophy','isbn':'978-1599869773','year':'500BC','copies':5,'copies_available':5},
            {'id':'b011','title':'Design Patterns','author':'Gang of Four','category':'Computer Science','isbn':'978-0201633610','year':'1994','copies':2,'copies_available':0},
            {'id':'b012','title':'Thinking, Fast and Slow','author':'Daniel Kahneman','category':'Psychology','isbn':'978-0374533557','year':'2011','copies':4,'copies_available':3},
        ]
        for b in sample_books:
            b['added_date'] = datetime.now().isoformat()
        save_books(sample_books)

    if not get_users():
        sample_users = [
            {'id':'u001','name':'Alice Chen','email':'alice@uni.edu','phone':'+91 98765 43210','member_type':'Student','joined_date':datetime.now().isoformat()},
            {'id':'u002','name':'Bob Patel','email':'bob@uni.edu','phone':'+91 98765 43211','member_type':'Student','joined_date':datetime.now().isoformat()},
            {'id':'u003','name':'Carol Smith','email':'carol@uni.edu','phone':'+91 98765 43212','member_type':'Faculty','joined_date':datetime.now().isoformat()},
            {'id':'u004','name':'David Kim','email':'david@uni.edu','phone':'+91 98765 43213','member_type':'Student','joined_date':datetime.now().isoformat()},
            {'id':'u005','name':'Eva Martinez','email':'eva@uni.edu','phone':'+91 98765 43214','member_type':'Student','joined_date':datetime.now().isoformat()},
        ]
        save_users(sample_users)

    if not get_borrows():
        now = datetime.now()
        sample_borrows = [
            {'id':'br001','book_id':'b001','user_id':'u001','borrow_date':(now-timedelta(days=10)).isoformat(),'due_date':(now+timedelta(days=4)).isoformat(),'returned':False,'return_date':None},
            {'id':'br002','book_id':'b003','user_id':'u001','borrow_date':(now-timedelta(days=20)).isoformat(),'due_date':(now-timedelta(days=6)).isoformat(),'returned':True,'return_date':(now-timedelta(days=7)).isoformat()},
            {'id':'br003','book_id':'b002','user_id':'u002','borrow_date':(now-timedelta(days=5)).isoformat(),'due_date':(now+timedelta(days=9)).isoformat(),'returned':False,'return_date':None},
            {'id':'br004','book_id':'b006','user_id':'u003','borrow_date':(now-timedelta(days=15)).isoformat(),'due_date':(now-timedelta(days=1)).isoformat(),'returned':False,'return_date':None},
            {'id':'br005','book_id':'b007','user_id':'u002','borrow_date':(now-timedelta(days=8)).isoformat(),'due_date':(now+timedelta(days=6)).isoformat(),'returned':False,'return_date':None},
            {'id':'br006','book_id':'b004','user_id':'u004','borrow_date':(now-timedelta(days=12)).isoformat(),'due_date':(now+timedelta(days=2)).isoformat(),'returned':False,'return_date':None},
            {'id':'br007','book_id':'b009','user_id':'u005','borrow_date':(now-timedelta(days=3)).isoformat(),'due_date':(now+timedelta(days=11)).isoformat(),'returned':False,'return_date':None},
            {'id':'br008','book_id':'b012','user_id':'u003','borrow_date':(now-timedelta(days=25)).isoformat(),'due_date':(now-timedelta(days=11)).isoformat(),'returned':True,'return_date':(now-timedelta(days=12)).isoformat()},
            {'id':'br009','book_id':'b005','user_id':'u001','borrow_date':(now-timedelta(days=18)).isoformat(),'due_date':(now-timedelta(days=4)).isoformat(),'returned':True,'return_date':(now-timedelta(days=5)).isoformat()},
            {'id':'br010','book_id':'b011','user_id':'u002','borrow_date':(now-timedelta(days=2)).isoformat(),'due_date':(now+timedelta(days=12)).isoformat(),'returned':False,'return_date':None},
        ]
        save_borrows(sample_borrows)

if __name__ == '__main__':
    os.makedirs(DATA_DIR, exist_ok=True)
    seed_data()
    app.run(debug=True, port=5000)
