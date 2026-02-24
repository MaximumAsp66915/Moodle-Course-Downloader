# Run the docker container to download files
Write-Host "Starting Moodle Downloader..."
docker-compose up --build

# Check if docker ran successfully (assuming it exits with 0)
if ($?) {
    Write-Host "Download complete. Syncing with GitHub..."
    
    # Go back to root
    cd ..
    
    # Add changes
    git add Courses/
    
    # Check if there are changes
    $status = git status --porcelain
    if ($status) {
        git commit -m "Auto-update course materials from local run"
        git push
        Write-Host "Successfully pushed new files to GitHub!"
    } else {
        Write-Host "No new files to push."
    }
} else {
    Write-Host "Docker run failed. Please check logs."
}
