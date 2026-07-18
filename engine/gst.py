# engine/gst.py

from datetime import date, timedelta
from core.schemas import CompanySnapshot, GSTEvent, GSTCalendar
from core.config import DEMO_DATE, GST_ANNUAL_DATES, GST_URGENT_DAYS, GST_UPCOMING_DAYS

def gst_calendar(snap: CompanySnapshot) -> GSTCalendar:
    events = []
    # Simplified mapping for demo purposes.
    month_map = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
        "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
    }
    
    for desc, dom in GST_ANNUAL_DATES:
        try:
            # Extract month from desc e.g. "GSTR-3B (Jul)"
            month_str = desc.split("(")[1].split(")")[0]
            m = month_map[month_str]
        except (IndexError, KeyError):
            continue
            
        # Calculate date for this year
        y = DEMO_DATE.year
        event_date = date(y, m, dom)
        
        # If it's already past by more than 30 days, check next year
        if event_date < DEMO_DATE - timedelta(days=30):
            event_date = date(y + 1, m, dom)
            
        days_until = (event_date - DEMO_DATE).days
        
        if days_until < 0:
            urgency = "OVERDUE"
        elif days_until <= GST_URGENT_DAYS:
            urgency = "URGENT"
        elif days_until <= GST_UPCOMING_DAYS:
            urgency = "UPCOMING"
        else:
            urgency = "FUTURE"
            
        # Optional: check if there's a payable row matching this
        amount = None
        for p in snap.payables:
            if p.category == "tax" and p.due_date == event_date:
                amount = p.amount
                break
                
        events.append(GSTEvent(
            description=desc,
            due_date=event_date,
            amount=amount,
            days_until_due=days_until,
            urgency=urgency
        ))
        
    events = sorted(events, key=lambda e: e.due_date)
    
    # Filter to only relevant upcoming or overdue events (e.g., next 90 days)
    upcoming_events = [e for e in events if -30 <= e.days_until_due <= 90]
    next_due = upcoming_events[0] if upcoming_events else None
    
    return GSTCalendar(
        events=tuple(upcoming_events),
        next_due=next_due
    )
