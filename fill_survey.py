import re
import sqlite3
from datetime import datetime
from pathlib import Path
import time
from typing import Optional, Tuple
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

URL = "https://cookiemagic.smg.com/"

import time

def is_comment_page(page) -> bool:
    """
    Detects the free-text comment page that asks for 3+ sentences.
    Looks for textarea #S000046 or its wrapper #FNSS000046.
    """
    try:
        page.wait_for_selector("#S000046, #FNSS000046", state="visible", timeout=1500)
        return page.locator("#S000046").count() > 0
    except PWTimeoutError:
        return False


def handle_comment_page(
    page,
    text: str = (
        "The staff was friendly and the store felt clean and welcoming. "
        "My order was prepared correctly and the cookies were fresh and warm. "
        "Checkout was quick and the pickup process was straightforward. "
        "Overall, the visit was smooth and I left feeling very satisfied."
    )
) -> bool:
    """
    If on the comment page, fills the textarea with a 3+ sentence response and clicks Next.
    Returns True if handled.
    """
    if not is_comment_page(page):
        return False

    # Enforce the 1200 char limit the page advertises (safe guard)
    text = text[:1180]  # keep some headroom for safety

    try:
        # Fill the textarea
        page.fill("#S000046", text)

        # Some SMG pages track user typing; fire events to be safe
        page.dispatch_event("#S000046", "input")
        page.dispatch_event("#S000046", "change")

        # Optional: brief pause so any live counters/gauges update
        page.wait_for_timeout(300)

        # Continue
        page.click("#NextButton", timeout=4000)
        print("[info] Comment filled (3+ sentences) -> Next clicked.")
        return True
    except PWTimeoutError:
        print("[warn] Could not fill comment or click Next.")
        return False

def is_prior_visit_yesno_page(page) -> bool:
    """
    Detects the Yes/No page:
      Row id: #FNSR000127
      Radios: #R000127.1 (Yes), #R000127.2 (No)
    """
    try:
        page.wait_for_selector("#FNSR000127", state="visible", timeout=1500)
        return page.locator("input#R000127\\.1, input#R000127\\.2").count() > 0
    except PWTimeoutError:
        return False

def handle_prior_visit_yesno_page(page, answer_no: bool = True) -> bool:
    """
    Selects 'No' by default (answer_no=True). If answer_no=False, selects 'Yes'.
    Clicks Next. Returns True if handled.
    """
    if not is_prior_visit_yesno_page(page):
        return False

    # Map desired choice to radio suffix: 1=Yes, 2=No
    val = "2" if answer_no else "1"
    label_selector = f"label[for='R000127.{val}']"
    cell_selector  = f"tr#FNSR000127 td.Opt{val}.inputtyperbloption"

    try:
        if page.locator(label_selector).count() > 0:
            page.click(label_selector, timeout=2000)   # radios are hidden; click label
        else:
            page.click(cell_selector, timeout=2000)    # fallback: click the cell

        page.click("#NextButton", timeout=4000)
        print(f"[info] Prior visit answered -> {'No' if answer_no else 'Yes'} -> Next clicked.")
        return True
    except PWTimeoutError:
        print("[warn] Could not answer prior-visit Yes/No or click Next.")
        return False

def is_email_capture_page(page) -> bool:
    """
    Detects the final email capture page (fields #S000061 and #S000062).
    """
    try:
        page.wait_for_selector("#S000061, #S000062", state="visible", timeout=1500)
        return page.locator("#S000061").count() > 0 and page.locator("#S000062").count() > 0
    except PWTimeoutError:
        return False


def handle_email_capture_page(page, email: str = "aashrithsai@gmail.com") -> bool:
    """
    Fills both Email and Confirm Email fields, then clicks Next.
    Returns True if handled.
    """
    if not is_email_capture_page(page):
        return False

    try:
        # Fill both fields with the same email
        page.fill("#S000061", email)
        page.dispatch_event("#S000061", "input")
        page.dispatch_event("#S000061", "change")

        page.fill("#S000062", email)
        page.dispatch_event("#S000062", "input")
        page.dispatch_event("#S000062", "change")

        page.wait_for_timeout(300)  # let live validation update

        page.click("#NextButton", timeout=4000)
        print(f"[info] Email filled ({email}) -> Next clicked.")
        return True
    except PWTimeoutError:
        print("[warn] Could not fill email fields or click Next.")
        return False

def run_router(page, inactivity_timeout_ms=20_000):
    """
    Continuously looks for known pages and handles them.
    Stops if no handler takes action within inactivity_timeout_ms.
    """
    # (detector_fn, handler_fn, kwargs) in the order you want to try
    steps = [
    (is_experience_page,            handle_experience_page,            {"choice": "pickup"}),
    (is_overall_satisfaction_page,  handle_overall_satisfaction_page,  {"score": 5}),
    (is_reason_page,                handle_reason_page,                {"reason": "treat_myself"}),
    (is_purchases_page,             handle_purchases_page,             {"purchases": ("cookies",), "other_text": ""}),
    (is_likelihood_page,            handle_likelihood_page,            {"recommend": 5, "ret": 5}),
    (is_cookie_quality_page,        handle_cookie_quality_page,        {"score": 5}),
    (is_comment_page,               handle_comment_page,               {"text": (
        "The staff was friendly and the store felt clean and welcoming. "
        "My order was prepared correctly and the cookies were fresh and warm. "
        "Checkout was quick and the pickup process was straightforward. "
        "Overall, the visit was smooth and I left feeling very satisfied."
    )}),
    (is_prior_visit_yesno_page,     handle_prior_visit_yesno_page,     {"answer_no": True}),
    # NEW: Email capture page
    (is_email_capture_page,         handle_email_capture_page,         {"email": "aashrithsai@gmail.com"}),
    ]



    last_action = time.time()
    poll_sleep = 0.25  # seconds between scans

    while True:
        # Exit cleanly if the page/browser was closed externally
        if page.is_closed():
            print("[info] Page was closed; stopping router.")
            return

        acted = False

        for detector, handler, kwargs in steps:
            try:
                if detector(page):               # fast check: is this page?
                    if handler(page, **kwargs):  # act + click Next inside the handler
                        acted = True
                        last_action = time.time()
                        # Give the site time to render the next page
                        page.wait_for_timeout(600)
                        break  # restart scanning from the top (priorities preserved)
            except Exception as e:
                # Non-fatal: log and continue scanning others
                print(f"[warn] Handler error in {handler.__name__}: {e}")

        if acted:
            continue  # immediately rescan from the top

        # No handler took action on this iteration
        if (time.time() - last_action) * 1000 >= inactivity_timeout_ms:
            print("[info] Router inactivity timeout reached; stopping.")
            return

        # Light sleep to avoid busy-waiting
        try:
            page.wait_for_timeout(int(poll_sleep * 1000))
        except Exception:
            print("[info] Page closed during poll wait; stopping router.")
            return


def is_overall_satisfaction_page(page) -> bool:
    """
    Detects the 'overall satisfaction' scale page (row id #FNSR000002).
    Returns True if present/visible.
    """
    try:
        page.wait_for_selector("#FNSR000002", state="visible", timeout=1500)
        # Sanity: make sure at least one of the radios exists
        return page.locator("input#R000002\\.1, input#R000002\\.2, input#R000002\\.3, input#R000002\\.4, input#R000002\\.5").count() > 0
    except PWTimeoutError:
        return False

def handle_overall_satisfaction_page(page, score: int = 5) -> bool:
    """
    If on the overall satisfaction page, select a score (1..5; 5=Highly Satisfied) and click Next.
    Returns True if handled, False otherwise.
    """
    if not is_overall_satisfaction_page(page):
        return False

    # Clamp score to valid range
    score = max(1, min(5, int(score)))

    # Prefer clicking the label tied to the hidden radio input
    label_selector = f"label[for='R000002.{score}']"
    # Fallback: click the cell container if label is absent
    cell_selector = f"tr#FNSR000002 td.Opt{score}.inputtyperbloption"

    try:
        if page.locator(label_selector).count() > 0:
            page.click(label_selector, timeout=2000)
        else:
            page.click(cell_selector, timeout=2000)

        # Proceed
        page.click("#NextButton", timeout=4000)
        print(f"[info] Overall satisfaction = {score} selected -> Next clicked.")
        return True
    except PWTimeoutError:
        print("[warn] Could not select overall satisfaction or click Next.")
        return False

def get_user_email():
    email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    while True:
        user_email = input("Which email address should I send code to? : ").strip()
        if re.match(email_regex, user_email):
            print(f"Thanks! Using email: {user_email}")
            return user_email
        else:
            print("That doesn’t look like a valid email. Try again.")

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

def is_experience_page(page) -> bool:
    """
    Returns True if the page matches the 'Which of the following best describes your experience?'
    screen (fieldset #FNSR000082 with radios R000082.1/2/3).
    """
    try:
        # Wait briefly; don't hard fail if it isn't this page
        page.wait_for_selector("#FNSR000082", state="visible", timeout=1500)
        # Sanity: one of the known radio inputs must exist
        return page.locator("input#R000082\\.1, input#R000082\\.2, input#R000082\\.3").count() > 0
    except PWTimeoutError:
        return False

def handle_experience_page(page, choice: str = "pickup"):
    """
    If on the experience page, choose one of: 'in_person', 'pickup', 'delivery'
    and click Next. Does nothing if not on that page.
    """
    if not is_experience_page(page):
        return False  # not this page

    # Map friendly choice -> radio id suffix
    mapping = {
        "in_person": "1",   # R000082.1
        "pickup": "2",      # R000082.2
        "delivery": "3",    # R000082.3
    }
    val = mapping.get(choice.lower(), "2")  # default to 'pickup'

    # Inputs are display:none; click the <label for="R000082.X"> to toggle
    label_selector = f"label[for='R000082.{val}']"
    # If label isn't clickable for some reason, click the option container as a fallback
    option_selector = f"div.rbList .Opt{val}.rbloption"

    try:
        if page.locator(label_selector).count() > 0:
            page.click(label_selector, timeout=2000)
        else:
            page.click(option_selector, timeout=2000)

        # Optional: verify aria-checked changed (robustness)
        # Not strictly required; many SMG templates update hidden input.
        # Just proceed to Next.
        page.click("#NextButton", timeout=4000)
        print("[info] Experience page answered -> Next clicked.")
        return True
    except PWTimeoutError:
        print("[warn] Could not select experience option or click Next.")
        return False

def is_reason_page(page) -> bool:
    """
    Detects the 'reason for choosing CookieLab' page (#FNSR000083).
    """
    try:
        page.wait_for_selector("#FNSR000083", state="visible", timeout=1500)
        return page.locator("input#R000083\\.1, input#R000083\\.2, input#R000083\\.3, input#R000083\\.4, input#R000083\\.99").count() > 0
    except PWTimeoutError:
        return False

def handle_reason_page(page, reason: str = "treat_myself") -> bool:
    """
    If on the reason page, selects one of:
      - 'day_out_with_children' (1)
      - 'hanging_out'          (2)
      - 'treat_myself'         (3)
      - 'unplanned'            (4)
      - 'other'                (99)
    Then clicks Next. Returns True if handled.
    """
    if not is_reason_page(page):
        return False

    mapping = {
        "day_out_with_children": "1",
        "hanging_out": "2",
        "treat_myself": "3",
        "unplanned": "4",
        "other": "99",
    }
    val = mapping.get(reason.lower(), "3")  # default to 'treat_myself'

    label_selector = f"label[for='R000083.{val}']"
    cell_selector  = f"div.rbList .Opt{val}.rbloption"

    try:
        if page.locator(label_selector).count() > 0:
            page.click(label_selector, timeout=2000)
        else:
            page.click(cell_selector, timeout=2000)

        page.click("#NextButton", timeout=4000)
        print(f"[info] Reason selected ({reason}) -> Next clicked.")
        return True
    except PWTimeoutError:
        print("[warn] Could not select reason or click Next.")
        return False

def is_purchases_page(page) -> bool:
    try:
        page.wait_for_selector("fieldset.inputtypeopt", state="visible", timeout=1500)
        # ensure at least one of the known checkbox inputs exists
        return page.locator("input#R000086, input#R000087, input#R000088").count() > 0
    except PWTimeoutError:
        return False

def handle_purchases_page(page, purchases=("cookies",), other_text: str = "") -> bool:
    """
    purchases: any of ('cookies','milkshake','other'); multi-select supported.
    If 'other' in purchases and other_text provided, fills the other textbox.
    """
    if not is_purchases_page(page):
        return False

    id_map = {
        "cookies":   "R000086",
        "milkshake": "R000087",
        "other":     "R000088",
    }

    try:
        # Click labels tied to hidden checkboxes
        for item in purchases:
            key = item.lower().strip()
            if key not in id_map:
                continue
            rid = id_map[key]
            page.click(f"label[for='{rid}']", timeout=1500)

            # If 'other', optionally fill the textbox
            if rid == "R000088" and other_text:
                # Other textbox is revealed after checking 'Other'
                page.fill("#R000088Other", other_text)

        page.click("#NextButton", timeout=4000)
        print(f"[info] Purchases selected: {purchases} -> Next clicked.")
        return True
    except PWTimeoutError:
        print("[warn] Could not complete purchases page.")
        return False


# --- Likelihood scales (two rows: recommend + return) ---
def is_likelihood_page(page) -> bool:
    try:
        # Look for either row id (both should be present on this page)
        page.wait_for_selector("#FNSR000043, #FNSR000116", state="visible", timeout=1500)
        return True
    except PWTimeoutError:
        return False

def handle_likelihood_page(page, recommend: int = 5, ret: int = 5) -> bool:
    """
    Selects scores for:
      - Recommend CookieLab?     -> R000043.(1..5)
      - Return to this CookieLab -> R000116.(1..5)
    5 is 'Highly Likely', 1 is 'Not At All Likely'.
    """
    if not is_likelihood_page(page):
        return False

    def clamp(n): return max(1, min(5, int(n)))
    recommend = clamp(recommend)
    ret = clamp(ret)

    try:
        # Prefer clicking labels for hidden radios
        page.click(f"label[for='R000043.{recommend}']", timeout=1500)
    except PWTimeoutError:
        # Fallback: click the cell (e.g., td.Opt5)
        page.click(f"tr#FNSR000043 td.Opt{recommend}.inputtyperbloption", timeout=1500)

    try:
        page.click(f"label[for='R000116.{ret}']", timeout=1500)
    except PWTimeoutError:
        page.click(f"tr#FNSR000116 td.Opt{ret}.inputtyperbloption", timeout=1500)

    try:
        page.click("#NextButton", timeout=4000)
        print(f"[info] Likelihood set -> recommend={recommend}, return={ret} -> Next clicked.")
        return True
    except PWTimeoutError:
        print("[warn] Could not click Next on likelihood page.")
        return False
    
# --- Cookie quality satisfaction (1–5 scale) ---
def is_cookie_quality_page(page) -> bool:
    """
    Detects the 'quality of your cookies' satisfaction page (#FNSR000090).
    """
    try:
        page.wait_for_selector("#FNSR000090", state="visible", timeout=1500)
        return page.locator("input#R000090\\.1, input#R000090\\.2, input#R000090\\.3, input#R000090\\.4, input#R000090\\.5").count() > 0
    except PWTimeoutError:
        return False

def handle_cookie_quality_page(page, score: int = 5) -> bool:
    """
    If on the cookie quality satisfaction page, select score (1..5; 5 = Highly Satisfied)
    and click Next. Returns True if handled.
    """
    if not is_cookie_quality_page(page):
        return False

    score = max(1, min(5, int(score)))  # clamp

    label_selector = f"label[for='R000090.{score}']"
    cell_selector  = f"tr#FNSR000090 td.Opt{score}.inputtyperbloption"

    try:
        if page.locator(label_selector).count() > 0:
            page.click(label_selector, timeout=2000)
        else:
            page.click(cell_selector, timeout=2000)

        page.click("#NextButton", timeout=4000)
        print(f"[info] Cookie quality satisfaction = {score} -> Next clicked.")
        return True
    except PWTimeoutError:
        print("[warn] Could not select cookie quality or click Next.")
        return False


def open_and_fill_cookiemagic():
    url = URL  # use the module-level constant

    # Data to fill (receipt gate)
    store_number = "0057"
    order_number = "2073439390"
    visit_month, visit_day, visit_year = "03", "09", "2026"
    time_hour, time_minute, time_ampm = "01", "00", "AM"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        # Explicitly start fresh (new context is already clean, but this is explicit)
        context.clear_cookies()
        print("[info] Cleared all cookies for new context.")

        page = context.new_page()
        print(f"[info] Navigating to {url} …")
        page.goto(url, wait_until="domcontentloaded")

        # Ensure the survey container is present
        page.wait_for_selector("#surveyQuestions", state="visible", timeout=10000)

        # Fill the receipt gate by exact IDs
        page.fill("#InputStoreNum", store_number)
        page.fill("#InputOrderNum02", order_number)

        page.wait_for_timeout(300)
        page.select_option("#InputMonth", value=visit_month)
        page.select_option("#InputDay", value=visit_day)
        page.select_option("#InputYear", value=visit_year)

        page.wait_for_timeout(300)
        page.select_option("#InputHour", value=time_hour)
        page.select_option("#InputMinute", value=time_minute)
        page.select_option("#InputMeridian", value=time_ampm)

        page.wait_for_timeout(300)
        print("[info] Form fields filled.")

        # Screenshot for verification
        page.screenshot(path="autofilled.png", full_page=True)
        print("[info] Saved screenshot -> autofilled.png")

        # Click Start
        try:
            page.click("#NextButton", timeout=5000)
            print("[info] Clicked Start.")
        except PWTimeoutError:
            print("[warn] Could not find/click Start button (#NextButton).")

        run_router(page, inactivity_timeout_ms=20_000)

        # Optional: keep window open briefly for inspection after routing ends
        if not page.is_closed():
            page.wait_for_timeout(2000)

        context.close()
        browser.close()

if __name__ == "__main__":
    # get_user_email()
    open_and_fill_cookiemagic()
