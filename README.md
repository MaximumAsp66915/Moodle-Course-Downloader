# 📚 Moodle Course Downloader

A free bot that **logs in to Sharif CourseWare (<https://cw.sharif.ir>) for you, every day, and saves all your course files** (slides, homework, resources) into your own GitHub page. 🤖

You do **not** need to know how to code. Everything below can be done by clicking in your web browser. 🖱️

---

## ✅ What you need

- 🌐 A web browser
- 🐙 A free GitHub account (sign up at <https://github.com/signup>)
- 🎓 Your CourseWare **username** and **password**

---

## 🚀 Easiest way: use the template (about 5 minutes)

You do **not** need to download, copy or push anything. GitHub does the copying for you.

### Step 1️⃣ Make your own copy

1. Open this page in your browser and make sure you are logged in to GitHub.
2. Click the green button **Use this template** (top right, above the file list).
3. Click **Create a new repository**.
4. Type any name in **Repository name** (for example `my-courses`).
5. ⚠️ **VERY IMPORTANT:** choose **Private** (the lock icon 🔒). Your course files and homework will be saved in this repository. If you pick Public, **everybody on the internet can download them.**
6. Click **Create repository**. Wait a few seconds until your new repository opens.

> 💡 Please use **Use this template** and **not** the **Fork** button. A fork of a public project can never be private.

### Step 2️⃣ Save your username and password safely 🔑

Your password is stored in a locked GitHub safe called *Secrets*. Nobody can read it, not even you later. It is also not shown in the logs.

1. In **your new repository**, click **Settings** (the tab with the ⚙️ gear, top right of the page).
2. On the left, click **Secrets and variables**, then click **Actions**.
3. Click the green button **New repository secret**.
4. In **Name** type exactly `MOODLE_USERNAME` (capital letters, with the underscore).
   In **Secret** type your CourseWare username. Click **Add secret**.
5. Click **New repository secret** again.
   In **Name** type exactly `MOODLE_PASSWORD`.
   In **Secret** type your CourseWare password. Click **Add secret**.

### Step 3️⃣ Start the bot ▶️

1. Click the **Actions** tab (top of your repository).
2. If GitHub shows a green button **I understand my workflows, go ahead and enable them**, click it.
3. On the left, click **Moodle Downloader**.
4. Click the **Run workflow** button (on the right), then click the green **Run workflow** button again.
5. Wait 5 to 10 minutes ⏳. Refresh the page. A green ✅ means it worked. A red ❌ means something went wrong (see *Problems* below).

### Step 4️⃣ Look at your files 📂

Go back to the **Code** tab of your repository. You will now see these new folders:

```
Courses/          <- courses of the latest semester
└── <Course Name>/
    ├── Slides/
    ├── Homework/      (assignment files + your own submissions in "Sent Files/")
    └── Resources/
Past-Courses/     <- courses of older semesters (same structure)
```

To download everything to your computer: click the green **Code** button, then **Download ZIP**. 🗜️

### 🎉 That's all!

From now on the bot runs **by itself every day at 12:00 UTC** and adds new files. You can also run it again any time with **Actions → Moodle Downloader → Run workflow**.

---

## 💻 Other way: run it on your own computer (optional)

Use this only if you prefer not to use GitHub Actions.

1. Install **Docker Desktop** from <https://www.docker.com/products/docker-desktop/> and start it. 🐳
2. On this page click the green **Code** button, then **Download ZIP**, and unzip it.
3. Open the folder `Code`. Make a copy of the file `.env.example` and name the copy `.env`.
4. Open `.env` with Notepad and replace `your_username` and `your_password` with your real ones. Save the file.
5. Open a terminal inside the folder `Code` and type:
   ```bash
   docker-compose up --build
   ```
6. When it finishes, the folders `Courses` and `Past-Courses` appear next to the folder `Code`. 🎉

> 🔒 Never share your `.env` file with anybody. It contains your password.

---

## 🧠 Good to know

- 🔁 **Safe to repeat:** files that were already downloaded are skipped. Nothing is ever deleted or overwritten, so files you add by hand are safe.
- 📦 When a semester ends, its course is moved from `Courses/` to `Past-Courses/` automatically.
- 🧹 Course names are cleaned (no semester text and no course code in the folder name).
- 🤖 The login page has a picture code (captcha). The bot reads it automatically using the small model in the folder `Code/captcha`.
- 💸 A private repository is free. GitHub gives free accounts a monthly allowance of automatic-run time, and one daily run of this bot uses only a small part of it.
- 😴 GitHub pauses automatic runs in a repository when nothing has happened in it for 60 days. If that happens, open **Actions** and click the button to enable the workflow again.

---

## 🆘 Problems

| What you see | What to do |
| --- | --- |
| ❌ Red cross in **Actions** | Click the failed run, then click the step with the red mark to read the message. |
| Message: *MOODLE_USERNAME and/or MOODLE_PASSWORD secret is missing* | Redo **Step 2**. The names must be written exactly `MOODLE_USERNAME` and `MOODLE_PASSWORD`. |
| Login fails | Check your username and password in CourseWare in your browser. Then save them again in **Settings → Secrets and variables → Actions** (click the ✏️ pencil next to the secret). |
| The `Courses` folder is empty | The bot has not finished yet, or you have no enrolled courses. Wait and refresh. |
| Docker says *Permission denied* (Linux) | Run `sudo usermod -aG docker $USER`, then log out and log in again. |

---

## 🔐 Privacy

Your username and password are only used to log in to CourseWare. They stay in your own GitHub *Secrets* (or in your own `.env` file) and are never sent anywhere else.

## 📄 License

MIT, see the file `LICENSE`. 💙
