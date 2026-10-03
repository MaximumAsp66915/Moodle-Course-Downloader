import os
import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
from dotenv import load_dotenv
import logging
import shutil
import sys
from tqdm import tqdm

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load Environment Variables
load_dotenv()

MOODLE_URL = os.getenv("MOODLE_URL", "https://cw.sharif.ir").rstrip("/")
USERNAME = os.getenv("MOODLE_USERNAME")
PASSWORD = os.getenv("MOODLE_PASSWORD")

if not USERNAME or not PASSWORD:
    logger.error("Username or Password not found in environment variables.")
    exit(1)

# Session Setup
cl = requests.Session()
cl.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

LOGIN_MAX_ATTEMPTS = 5
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _solve(image_bytes):
    from captcha.adapter import solve_captcha
    return solve_captcha(image_bytes)


def _is_login_page(text):
    return 'id="login"' in text and "logintoken" in text


def login():
    """Logs into the new CW (Moodle + login captcha) and establishes a session."""
    login_url = urljoin(MOODLE_URL, "/login/index.php")
    captcha_url = urljoin(MOODLE_URL, "/local/logincaptcha/image.php")

    for attempt in range(1, LOGIN_MAX_ATTEMPTS + 1):
        try:
            r = cl.get(login_url)
            r.raise_for_status()
            token_tag = BeautifulSoup(r.text, 'html.parser').select_one("input[name='logintoken']")
            token = token_tag.get('value', '') if token_tag else ''

            img = cl.get(captcha_url, headers={'Referer': login_url})
            img.raise_for_status()
            code = _solve(img.content).strip()
            logger.info(f"Login attempt {attempt}: captcha guess '{code}'")

            r = cl.post(login_url, data={
                'anchor': '', 'logintoken': token,
                'username': USERNAME, 'password': PASSWORD,
                'logincaptcha': code,
            }, headers={'Referer': login_url, 'Origin': MOODLE_URL})
            r.raise_for_status()
        except Exception as e:
            logger.error(f"Login attempt {attempt} failed: {e}")
            continue

        if "login/logout.php" in r.text and not _is_login_page(r.text):
            logger.info("Login successful!")
            return True

        err = BeautifulSoup(r.text, 'html.parser').select_one("#loginerrormessage, .loginerrors, .alert-danger")
        msg = err.get_text(strip=True) if err else ''
        low = msg.lower()
        if msg and not any(m in low for m in ("captcha", "کپچا", "کد امنیتی", "تصویر امنیتی")) \
                and any(m in low for m in ("نام کاربری", "رمز", "invalid", "incorrect", "password")):
            logger.error(f"Credentials rejected: {msg}")
            return False
        logger.info(f"Captcha attempt {attempt} failed: {msg or '?'}")

    logger.error("Login failed after all captcha attempts.")
    return False

COURSES_DIR = "Courses"
PAST_DIR = "Past-Courses"

_ASCII_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_CODE_RE = re.compile(r"(?<!\d)(\d{4})([123])\s*[-–]\s*(\d{5,})(?!\d)")
_TERM_RE = re.compile(r"نیمسال\s*(اول|دوم|سوم|پاییز|بهار|تابستان)\s*(?:سال\s*تحصیلی\s*)?(\d{4})")
_TERM_NAMES = {"اول": 1, "پاییز": 1, "دوم": 2, "بهار": 2, "سوم": 3, "تابستان": 3}


def parse_course_title(raw):
    """Returns (clean_name, term) from a raw CW title; term = year*10+semester or None.

    Handles e.g. 'درس: مدارهای واسطه - 25732 | نیمسال دوم سال تحصیلی 1404' and '14042-255581'.
    """
    text = " ".join((raw or "").split()).translate(_ASCII_DIGITS)
    term = None
    m = _CODE_RE.search(text)
    if m:
        term = int(m.group(1)) * 10 + int(m.group(2))
    m = _TERM_RE.search(text)
    if m:
        term = int(m.group(2)) * 10 + _TERM_NAMES[m.group(1)]
    name = re.sub(r"^درس\s*:\s*", "", text)
    name = name.split("|")[0]                              # drop "| نیمسال ..."
    name = _CODE_RE.sub("", name)
    name = re.sub(r"[\s_\-–]+(?:نیمسال.*)$", "", name)     # drop "_ نیمسال دوم ..."
    name = re.sub(r"\s*[-–]\s*\d{5,}\s*$", "", name)      # drop "- 25732"
    name = name.strip(" -–_|()[]")
    return name, term


def get_enrolled_courses():
    """Fetches enrolled courses with a clean name and term; skips non-course entries."""
    logger.info("Fetching enrolled courses...")
    urls_to_check = ["/my/courses.php", "/grade/report/overview/index.php", "/my/", "/user/profile.php"]

    courses = {}
    for relative_url in urls_to_check:
        dashboard_url = urljoin(MOODLE_URL, relative_url)
        try:
            soup = BeautifulSoup(cl.get(dashboard_url).text, 'html.parser')
        except Exception as e:
            logger.warning(f"Failed to check {dashboard_url}: {e}")
            continue

        for a_tag in soup.select("a[href*='/course/view.php?id='], a[href*='/course/user.php']"):
            cid_match = re.search(r'[?&]id=(\d+)', a_tag['href'])
            if not cid_match:
                continue
            cid = cid_match.group(1)
            parent = a_tag.find_parent(class_="course-item") or a_tag.find_parent(class_="coursebox")
            candidates = [a_tag.get('aria-label'), a_tag.get('title'), a_tag.get_text(" ", strip=True),
                          parent.get('data-shortname') if parent else None, parent.get('title') if parent else None]
            name, term = "", None
            for c in candidates:
                n, t = parse_course_title(c)
                if n and any(ch.isalpha() for ch in n):
                    name = name or n
                    term = term or t
            prev = courses.get(cid)
            if prev:
                name = prev['name'] or name
                term = prev['term'] or term
            if name:
                courses[cid] = {'name': name, 'term': term, 'id': cid,
                                'url': urljoin(MOODLE_URL, f"/course/view.php?id={cid}")}

    # Entries with no academic term (e.g. the system guide "راهنمای سامانه") are not courses.
    unique_courses = []
    for c in courses.values():
        if c['term'] is None:
            logger.info(f"Skipping non-course entry: {c['name']}")
        else:
            unique_courses.append(c)
    unique_courses.sort(key=lambda x: x['name'])

    if not unique_courses:
        logger.warning("No courses found. Check login or dashboard structure.")
        return unique_courses

    latest = max(c['term'] for c in unique_courses)
    for c in unique_courses:
        c['current'] = c['term'] == latest
        logger.info(f"Found Course: {c['name']} (term {c['term']}, {'current' if c['current'] else 'past'})")
    return unique_courses

def sanitize_filename(name):
    """Sanitizes strings to be safe for filenames."""
    # Replace invalid characters and extensive whitespace
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', ' ', name) # Collapse multiple spaces
    name = name.strip().strip('.')
    # Ensure filename is not empty
    if not name:
        name = "unnamed_item"
    return name

def download_file(url, folder, filename=None):
    """Downloads a file to the specified folder if it doesn't already exist."""
    if not os.path.exists(folder):
        os.makedirs(folder)

    # 1. Faster Check: If we already have a filename, check existence before any network call
    if filename:
        filename = sanitize_filename(filename)
        filepath = os.path.join(folder, filename)
        if os.path.exists(filepath):
            # Optional: Check size if needed, but existence is usually enough
            logger.info(f"File exists (skipping download): {filename}")
            return

    try:
        # 2. Network Check: If filename unknown, we must fetch headers to get the name
        # use a HEAD request first to get headers without downloading body
        # (Only if we didn't satisfy the check above)
        
        # Note: Moodle often redirects resource/view.php to the actual file.
        # HEAD requests follow redirects by default in newer requests, but let's be safe.
        with cl.get(url, stream=True) as r:
            r.raise_for_status()

            # Embed/"open" display mode: the page is HTML, the real file is linked inside it.
            if 'text/html' in r.headers.get('Content-Type', '').lower():
                page = BeautifulSoup(r.text, 'html.parser')
                main = page.select_one('#region-main, [role=main]') or page
                for a in main.select("a[href*='pluginfile.php']"):
                    link = urljoin(r.url, a['href'])
                    if link != url:
                        download_file(link, folder, filename=a.get_text(strip=True) or None)
                return

            # Determine filename from headers or URL
            final_filename = filename # inherit if we had one (but we would have returned above if it existed)
            
            if not final_filename:
                if "Content-Disposition" in r.headers:
                    cd = r.headers["Content-Disposition"]
                    # Handle utf-8 encoded filenames in content-disposition
                    # erratic, but standard is usually filename="name" or filename*=utf-8''name
                    fname_regex = re.findall(r'filename\*=utf-8\'\'(.+)|filename="?([^"]+)"?', cd)
                    if fname_regex:
                        # findall returns list of tuples [('name_utf', ''), ('', 'name_simple')]
                        # One of them will be non-empty
                        decoded_name = unquote(fname_regex[0][0] or fname_regex[0][1])
                        if decoded_name:
                             final_filename = decoded_name

                # Fallback to URL
                if not final_filename:
                    final_filename = os.path.basename(unquote(r.url)) or "downloaded_file"
            
            final_filename = sanitize_filename(final_filename)
            filepath = os.path.join(folder, final_filename)

            # Check existence AGAIN with the resolved filename
            if os.path.exists(filepath):
                logger.info(f"File exists (skipping download): {final_filename}")
                return

            # If we are here, we need to download.
            total_size = int(r.headers.get('content-length', 0))
            
            logger.info(f"Downloading: {final_filename} ({total_size} bytes)")

            with open(filepath, 'wb') as f, tqdm(
                desc=final_filename,
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
            ) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    bar.update(len(chunk))
            
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")

def move_course_between_roots(src, dst):
    """Merges src into dst (never overwriting) and removes src, so a course lives in one root only."""
    if not os.path.isdir(src):
        return
    logger.info(f"Moving {src} -> {dst}")
    for dirpath, _, files in os.walk(src):
        target_dir = os.path.join(dst, os.path.relpath(dirpath, src))
        os.makedirs(target_dir, exist_ok=True)
        for f in files:
            if not os.path.exists(os.path.join(target_dir, f)):
                shutil.move(os.path.join(dirpath, f), os.path.join(target_dir, f))
    shutil.rmtree(src, ignore_errors=True)


def process_course(course):
    """Scrapes content from a course page."""
    course_name = sanitize_filename(course['name'])
    course_url = course['url']
    
    logger.info(f"Processing Course: {course_name}")
    
    response = cl.get(course_url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Base Course Directory
    root, other = (COURSES_DIR, PAST_DIR) if course.get('current') else (PAST_DIR, COURSES_DIR)
    base_course_dir = os.path.join(root, course_name)
    move_course_between_roots(os.path.join(other, course_name), base_course_dir)
    os.makedirs(base_course_dir, exist_ok=True)

    # Sections (Topics/Weeks)
    # Moodle sections usually have ID 'section-X' or class 'section'
    sections = soup.select('li.course-section') or soup.select('.course-content .section')
    
    # Track downloaded URLs to avoid duplicates within a course run
    downloaded_urls = set()

    for section in sections:
        # Get section name
        section_name_tag = section.select_one('.sectionname') or section.find('span', class_='sectionname')
        section_name = section_name_tag.get_text(strip=True) if section_name_tag else "General"
        
        # Determine strict category ('Homework' or 'Slides' or 'Resources')
        # Heuristic: 
        # If 'homework' or 'assign' in section_name -> Homework
        # If 'slide' or 'lecture' or 'presentation' -> Slides
        # Else -> Keep original section name structure or 'Resources'
        
        category_dir = "Resources"
        lower_name = section_name.lower()
        if any(x in lower_name for x in ['homework', 'assignment', 'quiz', 'project', 'lab']):
            category_dir = "Homework"
        elif any(x in lower_name for x in ['slide', 'lecture', 'presentation', 'note']):
            category_dir = "Slides"
        
        # We might want to keep the section name as a subfolder if it's specific?
        # The user requested: Courses/Course 1/Homework1/Files...
        # So specific homework folders are better.
        
        current_dir = os.path.join(base_course_dir, category_dir)
        if category_dir == "Homework" and "homework" in lower_name:
             # E.g. section is "Homework 1" -> create 'Homework/Homework 1'
             current_dir = os.path.join(base_course_dir, "Homework", sanitize_filename(section_name))
        
        # Iterate over activities in the section
        # Standard Moodle uses 'ul.section li.activity', but strict hierarchy varies.
        # We look for any list item with class 'activity'
        activities = section.select('li.activity') or section.find_all(class_='activity')

        for activity in activities:
            # Identify type
            instancename_tag = activity.find(class_='instancename')
            if not instancename_tag:
                continue
            
            activity_name = instancename_tag.get_text(strip=True)
            # Remove " File" or " Folder" suffix text often hidden by CSS
            activity_name = activity_name.split("\n")[0].strip()

            link = activity.select_one('a.aalink[href]') or activity.find('a', href=True)
            if not link:
                continue
            
            href = link['href']
            
            # Avoid re-processing same link
            if href in downloaded_urls:
                continue
            downloaded_urls.add(href)
            
            # Decide folder based on activity type
            target_folder = current_dir

            # 1. Resource (File)
            if 'resource/view.php' in href:
                logger.info(f"Checking Resource: {activity_name}")
                # Moodle resource/view.php usually redirects to the file
                # or shows a page with a link.
                # We try to download directly.
                download_file(href, target_folder, filename=None) 
                
            # 2. Folder (Collection of files)
            elif 'folder/view.php' in href:
                logger.info(f"Checking Folder: {activity_name}")
                folder_specific_dir = os.path.join(target_folder, sanitize_filename(activity_name))
                if not os.path.exists(folder_specific_dir):
                    os.makedirs(folder_specific_dir)
                
                # Helper to download folder contents
                process_moodle_folder(href, folder_specific_dir)

            # 3. Assignment
            elif 'assign/view.php' in href:
                logger.info(f"Checking Assignment: {activity_name}")
                assign_dir = os.path.join(base_course_dir, "Homework", sanitize_filename(activity_name))
                if not os.path.exists(assign_dir):
                    os.makedirs(assign_dir)
                
                process_moodle_assignment(href, assign_dir)
        
        # NEW: Look for loose files inside the section description/content
        # Sometimes files are embedded directly as links in the text, not as activities.
        # Only look inside 'content' or 'summary' divs to avoid navigation links
        section_content = section.find(class_='content') or section.find(class_='summary')
        if section_content:
            loose_links = section_content.find_all('a', href=True)
            for link in loose_links:
                href = link['href']
                text = link.get_text(strip=True)
                
                # Check extension or moodle file pattern
                is_file = False
                lower_href = href.lower()
                if any(ext in lower_href for ext in ['.pdf', '.docx', '.pptx', '.zip', '.rar', '.7z', '.txt', '.py', '.c', '.cpp', '.java']):
                    is_file = True
                elif 'pluginfile.php' in lower_href and 'forcedownload=1' in lower_href:
                    is_file = True
                elif 'pluginfile.php' in lower_href and ('/mod_resource/' in lower_href or '/mod_folder/' in lower_href):
                     is_file = True

                if is_file and href not in downloaded_urls:
                    logger.info(f"Found loose file: {text}")
                    downloaded_urls.add(href)
                    # If it's loose in a section, put it in the current category dir (e.g. Slides or Resources)
                    download_file(href, current_dir, filename=text)

def process_moodle_folder(url, folder_path):
    """Downloads files from a Moodle Folder module."""
    try:
        resp = cl.get(url)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # Standard folder view lists files
        # Look for 'fp-filename-icon' which usually contains the download link
        files = soup.select('.fp-filename-icon a')
        if not files:
            # Fallback for some themes: look for any file link in 'folder_content'
            content = soup.find(class_='folder_content') or soup.find(id='region-main')
            if content:
                files = content.find_all('a', href=True)

        for f in files:
            f_url = f['href']
            # Filter valid download links (often contain 'pluginfile.php')
            if 'pluginfile.php' in f_url or 'forcedownload=1' in f_url:
                f_name = f.get_text(strip=True)
                download_file(f_url, folder_path, filename=f_name)

    except Exception as e:
        logger.error(f"Error processing folder {url}: {e}")

def process_moodle_assignment(url, folder_path):
    """Downloads files from a Moodle Assignment module."""
    try:
        resp = cl.get(url)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Instructor files usually in 'intro' section
        for l in soup.find_all('a', href=True):
            if 'mod_assign/introattachment' in l['href'] or ('pluginfile.php' in l['href'] and '/mod_assign/intro/' in l['href']):
                # Instructor provided file
                download_file(l['href'], folder_path, filename=l.get_text(strip=True))

        # Download Submitted Files (Sent files)
        # Look for submission status table or container
        submission_container = soup.find(class_='submissionstatustable') or soup.find(id='region-main')
        if submission_container:
            # Files are usually in a cell with class 'fileuploadsubmission' or similar
            # Search for any file links inside the submission container
            file_links = submission_container.find_all('a', href=True)
            
            sent_files_dir = os.path.join(folder_path, "Sent Files")
            
            for l in file_links:
                href = l['href']
                # Check for file download links
                if 'pluginfile.php' in href and 'assignsubmission_file' in href:
                    fname = l.get_text(strip=True)
                    download_file(href, sent_files_dir, filename=fname)
                    
    except Exception as e:
        logger.error(f"Error processing assignment {url}: {e}")

                            
    # Also fetch "Recent" files if possible?
    # Keeping it simple for now based on sections.

def main():
    if login():
        courses = get_enrolled_courses()
        logger.info(f"Found {len(courses)} courses.")
        for course in courses:
            process_course(course)
    else:
        logger.error("Cannot proceed without login.")
        exit(1)

if __name__ == "__main__":
    main()
