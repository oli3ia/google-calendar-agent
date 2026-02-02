import os
import sys
import datetime
from fastmcp import FastMCP
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# 1. set up and authorisation
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def get_calendar_service():
    base_path = os.path.dirname(os.path.abspath(__file__))
    creds_path = os.path.join(base_path, 'credentials2.json')
    token_path = os.path.join(base_path, 'token.json')

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing existing token...", file=sys.stderr)
            creds.refresh(Request())
        else:
            print(f"No valid token found. Starting full auth flow...", file=sys.stderr)
            # Use port 8080 specifically to avoid 'random port' issues
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=8080, prompt='consent')
        
        # --- THE CRITICAL SAVE STEP ---
        print(f"Attempting to save token to: {token_path}", file=sys.stderr)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
        print("Success! token.json has been created.", file=sys.stderr)
    
    return build('calendar', 'v3', credentials=creds)

# 2. initialise mcp
mcp = FastMCP("Google Calendar Agent") #server that LLM will connect to

# 3. the tool 
@mcp.tool()
def check_availability(start_iso: str, end_iso: str) -> str:
    """
    Checks all Google Calendars for conflicts between two ISO timestamps.
    Input format: '2026-01-28T14:00:00Z'
    """
    # zulu time format - safety
    if not start_iso.endswith('Z') and '+' not in start_iso:
        start_iso += 'Z'
    if not end_iso.endswith('Z') and '+' not in end_iso:
        end_iso += 'Z'

    service = get_calendar_service()
    
    try:
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        all_events = []
        
        for calendar in calendars:
            calendar_id = calendar['id']
            calendar_name = calendar.get('summary', 'Unknown')

            if any(x in calendar_name for x in ["Holidays", "Birthdays", "Contacts"]):
                continue

            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=start_iso,
                timeMax=end_iso,
                singleEvents=True,
                orderBy='startTime'
                ).execute()
            
            events = events_result.get('items', [])
            for e in events:
                start_time = e['start'].get('dateTime', e['start'].get('date'))
                all_events.append(f"{e['summary']} (on {calendar_name}) at {start_time}")

        if not all_events:
            return "You are completely free during this time"
        
        return f"Conflicts found: {', '.join(all_events)}"

    except Exception as e:
        return f"Error: {str(e)}"

@mcp.resource("calendar://weekly-summary")
def get_weekly_summary() -> str:
    """Returns a text-based overview of the next 7 days"""
    return "Monday: Free, Tuesday Busy 2-4pm..."


@mcp.tool()
def get_free_time(date_str: str) -> str:
    """Calculates free blocks for a specific date (YYYY-MM-DD)."""
    service = get_calendar_service()

    # Ensure timestamps are perfectly formatted
    day_start = f"{date_str}T00:00:00Z"
    day_end = f"{date_str}T23:59:59Z"

    # CRITICAL: This is the exact structure Google requires
    body = {
        "timeMin": day_start,
        "timeMax": day_end,
        "items": [{"id": "primary"}]
    }

    try:
        # Execute the query
        fb_result = service.freebusy().query(body=body).execute()
        
        # Dig into the response
        cal_data = fb_result.get('calendars', {}).get('primary', {})
        busy_slots = cal_data.get('busy', [])
        
    except Exception as e:
        import sys
        print(f"Google API Error: {e}", file=sys.stderr)
        return f"Error connecting to Google: {str(e)}"

    # --- Rest of your gap calculation logic ---
    if not busy_slots:
        return f"You are completely free on {date_str}."

    free_slots = []
    # Use 'fromisoformat' but handle the 'Z' correctly for Python 3.11+
    current_time = datetime.datetime.fromisoformat(day_start.replace('Z', '+00:00'))
    
    for slot in busy_slots:
        slot_start = datetime.datetime.fromisoformat(slot['start'].replace('Z', '+00:00'))
        slot_end = datetime.datetime.fromisoformat(slot['end'].replace('Z', '+00:00'))
        
        if slot_start > current_time:
            free_slots.append(f"{current_time.strftime('%H:%M')} - {slot_start.strftime('%H:%M')}")
        
        current_time = max(current_time, slot_end)

    end_boundary = datetime.datetime.fromisoformat(day_end.replace('Z', '+00:00'))
    if current_time < end_boundary:
        free_slots.append(f"{current_time.strftime('%H:%M')} - {end_boundary.strftime('%H:%M')}")

    return "Free slots:\n" + "\n".join(free_slots)



if __name__ == "__main__":
    print("--- PRE-FLIGHT AUTH CHECK ---", file=sys.stderr)
    try:
        # This triggers your function once to ensure token.json exists/refreshes
        get_calendar_service() 
        print("Auth successful! Starting MCP server...", file=sys.stderr)
    except Exception as e:
        print(f"Auth failed on startup: {e}", file=sys.stderr)
        sys.exit(1)

    # Now start the server
    mcp.run(transport="http", 
            host="0.0.0.0", 
            port=8000, 
            path="/mcp")