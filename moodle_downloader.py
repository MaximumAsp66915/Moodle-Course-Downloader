import os
import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
from dotenv import load_dotenv
import logging
from tqdm import tqdm

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load Environment Variables
load_dotenv()

MOODLE_URL = os.getenv("MOODLE_URL", "https://e.cw.sharif.edu")
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

def login():
    """Logs into Moodle and establishes a session."""
    login_url = urljoin(MOODLE_URL, "/login/index.php")
    
    logger.info(f"Navigating to login page: {login_url}")
    try:
        response = cl.get(login_url)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to load login page: {e}")
        return False

    soup = BeautifulSoup(response.text, 'html.parser')

    # Heuristic: Find the form that contains a password field
    login_form = None
    for form in soup.find_all('form'):
        if form.find('input', type='password'):
            login_form = form
            break
    
    if not login_form:
        logger.error("Could not find a login form on the page.")
        return False

    # Extract all hidden inputs (CSRF tokens, execution keys, etc.)
    payload = {}
    for input_tag in login_form.find_all('input', type='hidden'):
        if input_tag.get('name'):
            payload[input_tag['name']] = input_tag.get('value', '')

    # Add credentials
    # Moodle standard: 'username', 'password'
    # CAS standard: 'username', 'password' (sometimes 'ul' or similar)
    # We'll assume standard 'username' and 'password' fields exist or are named similarly
    
    # Try to find the exact name of the user/pass fields
    user_field = login_form.find('input', type='text') or login_form.find('input', type='email')
    pass_field = login_form.find('input', type='password')
    
    user_key = user_field.get('name', 'username') if user_field else 'username'
    pass_key = pass_field.get('name', 'password') if pass_field else 'password'

    payload[user_key] = USERNAME
    payload[pass_key] = PASSWORD

    # Determine POST URL
    action = login_form.get('action')
    post_url = urljoin(response.url, action) if action else response.url
    
    logger.info(f"Submitting credentials to {post_url}...")
    try:
        response = cl.post(post_url, data=payload)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Login failed: {e}")
        return False

    # Check for login success
    # If we are redirected to the dashboard or see a logout link, we are good.
    if "logout.php" in response.text or "Log out" in response.text:
        logger.info("Login successful!")
        return True
    elif "Invalid login" in response.text or "incorrect" in response.text.lower():
        logger.error("Invalid credentials.")
        return False
    else:
        # Check if we are still on the login page
        if "login" in response.url and "testsession" not in response.url:
             logger.warning("Unsure if login succeeded. Current URL mentions login.")
        else:
             logger.info("Login seems successful (redirected away from login).")
             return True
        return True # Optimistic approach

def get_enrolled_courses():
    """Fetches list of enrolled courses."""
    logger.info("Fetching enrolled courses...")
    courses = []
    
    # Try different URLs
    urls_to_check = ["/my/courses.php", "/my/", "/user/profile.php"]
    
    for relative_url in urls_to_check:
        dashboard_url = urljoin(MOODLE_URL, relative_url)
        logger.info(f"Checking for courses at: {dashboard_url}")
        
        try:
            response = cl.get(dashboard_url)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            headers = soup.find_all(['h3', 'h4', 'h5', 'a'])
            for h in headers:
                # Check if it has a link to course/view.php
                a_tag = h if h.name == 'a' else h.find('a')
                if a_tag and a_tag.get('href') and '/course/view.php?id=' in a_tag['href']:
                    name = a_tag.get_text(strip=True)
                    url = a_tag['href']
                    # Filter out garbage links or course categories
                    if name and len(name) > 2:
                        courses.append({'name': name, 'url': url})
        
        except Exception as e:
            logger.warning(f"Failed to check {dashboard_url}: {e}")
            
    # Deduplicate
    unique_courses = {}
    for c in courses:
        # Use course ID as unique key if possible
        cid_match = re.search(r'id=(\d+)', c['url'])
        cid = cid_match.group(1) if cid_match else c['url']
        if cid not in unique_courses:
             unique_courses[cid] = c
             
    result = list(unique_courses.values())
    
    # Sort them by name to be consistent across runs
    result.sort(key=lambda x: x['name'])
    
    if not result:
        logger.warning("No courses found. Check login or dashboard structure.")
        
    return result

def sanitize_filename(name):
    """Sanitizes strings to be safe for filenames."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

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

def process_course(course):
    """Scrapes content from a course page."""
    course_name = sanitize_filename(course['name'])
    course_url = course['url']
    
    logger.info(f"Processing Course: {course_name}")
    
    response = cl.get(course_url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Base Course Directory
    base_course_dir = os.path.join("Courses", course_name)
    if not os.path.exists(base_course_dir):
        os.makedirs(base_course_dir)

    # Sections (Topics/Weeks)
    # Moodle sections usually have ID 'section-X' or class 'section'
    sections = soup.select('.course-content .section')
    
    # Track downloaded URLs to avoid duplicates within a course run
    downloaded_urls = set()

    for section in sections:
        # Get section name
        section_name_tag = section.find('h3', class_='sectionname') or section.find('span', class_='sectionname')
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
        activities = section.find_all(class_='activity')

        for activity in activities:
            # Identify type
            instancename_tag = activity.find(class_='instancename')
            if not instancename_tag:
                continue
            
            activity_name = instancename_tag.get_text(strip=True)
            # Remove " File" or " Folder" suffix text often hidden by CSS
            activity_name = activity_name.split("\n")[0].strip()

            link = activity.find('a', href=True)
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
        intro = soup.find(class_='generalbox') or soup.find(id='intro')
        if intro:
            links = intro.find_all('a', href=True)
            for l in links:
                if 'pluginfile.php' in l['href']:
                     # Instructor provided file
                     fname = l.get_text(strip=True)
                     download_file(l['href'], folder_path, filename=fname)

        # Download Submitted Files (Sent files)
        # Look for submission status table or container
        submission_container = soup.find(class_='submissionstatustable')
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
