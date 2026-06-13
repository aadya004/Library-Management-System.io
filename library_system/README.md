# LibraCore – Library Management System

A full-featured admin panel built with **Flask + Python** for managing a modern library.

## Features

- **Book Management** – Add, edit, delete books; track copies & availability
- **User Registration** – Member profiles with types (Student, Faculty, Staff, External)
- **Search Engine** – Binary Search on title/author/category
- **Borrow & Return** – Issue books, track due dates, handle returns
- **Reservation Queue** – FIFO queue when books are unavailable
- **Recommendation Engine** – Graph-based (NetworkX) personalized suggestions
- **Analytics Dashboard** – Plotly charts: most borrowed, category popularity, trends, active users
- **Bulk Import** – CSV upload for books and users

## DSA Used

| Feature | Algorithm / Data Structure |
|---|---|
| Search | Binary Search (prefix + substring) |
| Reservations | FIFO Queue |
| Recommendations | Weighted Undirected Graph (NetworkX) |
| Analytics | Hash Maps (defaultdict) |

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Then open: http://localhost:5000

## Bulk Import CSV Format

### Books
```
title,author,category,isbn,year,copies
Clean Code,Robert C. Martin,Computer Science,978-0132350884,2008,3
```

### Users
```
name,email,phone,member_type
Jane Doe,jane@uni.edu,+91 98765 43210,Student
```

Sample files: `sample_books.csv` and `sample_users.csv`

## Project Structure

```
library_system/
├── app.py                  # Main Flask application
├── requirements.txt
├── sample_books.csv        # Bulk import sample
├── sample_users.csv        # Bulk import sample
├── data/                   # Auto-created JSON storage
│   ├── books.json
│   ├── users.json
│   ├── borrows.json
│   └── reservations.json
└── templates/
    ├── base.html
    ├── dashboard.html
    ├── books.html
    ├── book_form.html
    ├── users.html
    ├── user_form.html
    ├── borrow.html
    ├── reservations.html
    ├── recommendations.html
    └── analytics.html
```

## New Features (v2.0)

### 1. Notification Center
- **Real-time event tracking** for key library operations
- Notifications generated for:
  - Books borrowed
  - Books returned
  - User registration
  - Queue entry (when book unavailable)
  - Queue allocation (automatic assignment when book returns)
  - New books added to catalog
- **Storage**: `data/notifications.json`
- **Dashboard**: Shows latest 10 notifications with timestamps and event types

### 2. Demand Score System
- **Formula**: `Demand Score = Borrow Count + Queue Length`
- Identifies high-demand books in real-time
- **Dashboard Widget**: Top 5 demanded books displayed
- **API**: `get_demand_score(book_id)`
- Helps librarians prioritize acquisitions and shelf placement

### 3. Overdue Fine Calculator
- **Calculation**: ₹20 per day after due date
- Example: 3 days overdue = ₹60 fine
- **Fine Display Locations**:
  - Borrow page (active borrows table)
  - Dashboard overdue summary
  - Shows days overdue + total amount
- **Helper**: `calculate_fine(borrow_record)`

### 4. Enhanced Validation
- **ISBN Duplicate Check**: Prevents duplicate ISBNs
- **Email Duplicate Check**: Prevents duplicate user emails
- **Negative Copies Check**: Ensures non-negative stock
- **Empty Fields**: All required fields validated
- **Duplicate Queue Entries**: Prevents same user in queue multiple times
- Flash messages inform librarians of validation errors

### 5. Search Autocomplete
- **API Endpoint**: `GET /api/books/search?q=<query>`
- Returns up to 10 matching books by title/author
- Minimum 2 characters for search activation
- Response format: `[{id, title, author, category}, ...]`

### 6. Book Popularity Analytics
Using Pandas for deeper insights:
- **Top Borrowed Books** chart
- **Most Demanded Books** chart (by demand score)
- **Category Popularity** distribution
- **Average Borrow Duration** calculation
- **Most Active Members** ranking
- All integrated into Analytics Dashboard

### 7. Dashboard Enhancements
Added four new dashboard sections:

#### A. Recent Notifications Widget
- Latest 10 system events
- Color-coded by type (success/info/warning)
- Timestamps for tracking

#### B. Most Demanded Books Widget
- Top 5 books by demand score
- Shows title + author
- Demand score numeric display

#### C. Overdue Summary
- Total overdue books count
- Total pending fines (₹)
- Visual distinction for action needed

#### D. Quick Insights
- Most borrowed book title + author
- Most active member name + type
- Most popular category
- Single-glance operational metrics

### 8. Fine Management
- **Auto-calculation** on every page load
- **Display** in overdue records
- **Summary** in dashboard
- No payment gateway (calculation & display only)

### 9. OOP Implementation
Existing dataclasses (preserved as-is):
```python
@dataclass
class Book:
    id, title, author, category, isbn, year, copies, copies_available, added_date

@dataclass
class User:
    id, name, email, phone, member_type, joined_date

@dataclass
class BorrowRecord:
    id, book_id, user_id, borrow_date, due_date, returned, return_date
```
All entities have `from_dict()` and `to_dict()` for JSON serialization.

## API Reference

### New Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/books/search?q=<query>` | Search autocomplete |
| GET | `/api/recommendations/<user_id>` | Personalized recommendations |

### Helper Functions

| Function | Purpose |
|---|---|
| `get_demand_score(book_id)` | Calculate demand score |
| `get_most_demanded_books(n)` | Get top n books by demand |
| `calculate_fine(borrow_record)` | Calculate overdue fine |
| `get_overdue_summary()` | Get total overdue + fines |
| `create_notification(message, type)` | Log a notification |
| `get_recent_notifications(n)` | Fetch latest n notifications |

## Data Storage

All data persists in JSON format:

```
data/
├── books.json              # Book catalog
├── users.json              # User profiles
├── borrows.json            # Borrow records + history
├── reservations.json       # Queue assignments
└── notifications.json      # Event log (NEW)
```

## Business Logic Summary

| Feature | Behavior |
|---|---|
| **Notification** | Auto-generated on key events (borrow, return, signup, queue) |
| **Demand Score** | Real-time calculation; updated on borrow/return |
| **Fine** | ₹20/day; calculated automatically for overdue borrows |
| **Validation** | Prevents duplicates + empty fields; flash feedback |
| **Search** | Fast autocomplete; returns title/author matches |
| **Queue** | FIFO; auto-dequeue when book returned; FIFO allocation |
| **Recommendation** | Graph-based similarity; category + co-borrow edges |

