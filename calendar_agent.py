import os
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv
import google.generativeai as genai

# API Scopes and Gemini Key
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
# Loads  variables from .env
load_dotenv()
# Gets key from .env
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

# Authentication with Google
def get_calendar_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials2.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)

# Function Gemini will use to check your calendar
def check_availability(start_iso: str, end_iso: str):
    # --- SAFETY FIX: Ensure timestamps are RFC3339 compliant ---
    if not start_iso.endswith('Z') and '+' not in start_iso:
        start_iso += 'Z'
    if not end_iso.endswith('Z') and '+' not in end_iso:
        end_iso += 'Z'

    service = get_calendar_service()
    
    try:
        # Get all calendars
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        
        all_events = []
        
        # Search each calendar
        for calendar in calendars:
            calendar_id = calendar['id']
            calendar_name = calendar.get('summary', 'Unknown')

            # Skip holidays/birthdays to reduce noise
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
            return "You are completely free across all your calendars."
        
        return f"Conflicts found: {', '.join(all_events)}"

    except Exception as e:
        return f"Error querying calendars: {str(e)}"
    
# Configure Gemini
genai.configure(api_key=GOOGLE_API_KEY)

# Define the model with the tool
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash-lite',
    tools=[check_availability],
    system_instruction=f"You are a helpful calendar assistant. The current date/time is {datetime.datetime.now().isoformat()}. Use the check_availability tool to answer user questions about their schedule."
)

# Test query
chat = model.start_chat(enable_automatic_function_calling=True)

user_query = "Am I free on Monday 26th January 2026 at from 8pm to 9pm?"
print(f"User: {user_query}")

response = chat.send_message(user_query)
print(f"AI: {response.text}")