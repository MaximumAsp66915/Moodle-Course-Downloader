# Moodle Course Downloader

This python script automatically fetches course materials from your university's Moodle website (Sharif CourseWare) and organizes them into a structured folder hierarchy.

## Features

-   **Automatic Authentication**: Logs into Moodle using your credentials.
-   **Course Discovery**: Finds all enrolled courses.
-   **Structured Downloads**: 
    -   `Courses/`
        -   `Course Name/`
            -   `Slides/`
            -   `Homework/`
            -   `Resources/`
-   **GitHub Integration**: Can be run locally or via GitHub Actions (experimental due to firewalls).

## Local Setup (Docker)

This is the recommended way to run the script locally.

1.  **Clone the repository**:
    ```bash
    git clone <your-repo-url>
    cd <your-repo-folder>
    ```

2.  **Configure Credentials**:
    -   Copy `.env.example` to `.env`.
    -   Fill in your Moodle username and password.

3.  **Run with Docker Compose**:
    ```bash
    docker-compose up --build
    ```
    This will build the image and run the script. Files will be downloaded to the `Courses/` directory on your host machine.

## GitHub Actions Usage & Frequency

This workflow is configured to run **once a day** at 12:00 UTC.

-   **Zero Idle Usage**: When the script is not running, it uses **0% CPU** and **0 minutes** of your GitHub Actions quota. GitHub completely shuts down the environment after the job finishes.
-   **Efficiency**: The script checks if files already exist before downloading them. Subsequent runs will be very fast (detecting existing files) and will only download new content.
-   **Quota**: A typical run takes 1-3 minutes. With GitHub Pro/Education (3000 minutes/month), this will use less than 5% of your monthly allowance.


## Credits & License

This project is licensed under the MIT License - see the `LICENSE` file for details.

**Acknowledgement**: The core logic and code structure were generated with the assistance of **GitHub Copilot** (using the **Gemini 3 Pro (Preview)** model).

