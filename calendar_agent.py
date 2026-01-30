import os
import sys
import traceback
from mcp.server.fastmcp import FastMCP
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv

# 1. set up and authorisation
load_dotenv() # Loads  variables from .env
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def get_calendar_service():
    try:
        # absolute paths 
        base_path = os.path.dirname(os.path.abspath(__file__))
        creds_path = os.path.join(base_path, 'credentials2.json')
        token_path = os.path.join(base_path, 'token.json')

        creds = None
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            
        if not creds or not creds.valid:
            # If we reach here browser interaction needed 
            if not creds:
                raise Exception(f"No token found at {token_path}. Run 'python calendar_agent.py' manually first!")
            
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
        
        return build('calendar', 'v3', credentials=creds)

    except Exception as e:
        # This sends the error to your TERMINAL instead of the MCP stream
        print(f"\n--- GOOGLE AUTH ERROR ---\n{traceback.format_exc()}", file=sys.stderr)
        raise e

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

if __name__ == "__main__":
    mcp.run()