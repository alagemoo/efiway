// Updated app.js with logout functionality, enhanced error handling, and token expiry management

// DOM Elements
const loginForm = document.getElementById("loginForm");
const loginError = document.getElementById("loginError");
const loginSection = document.getElementById("loginSection");
const mainContent = document.getElementById("mainContent");
const questionForm = document.getElementById("questionForm");
const responseSection = document.getElementById("responseSection");
const fileStatus = document.getElementById("fileStatus");
const logoutButton = document.createElement("button");

// Check if user is authenticated
function isAuthenticated() {
    const token = localStorage.getItem("accessToken");
    if (!token) return false;

    try {
        const payload = JSON.parse(atob(token.split(".")[1]));
        const isExpired = payload.exp * 1000 < Date.now();
        if (isExpired) {
            logout();
            alert("Session expired. Please log in again.");
            return false;
        }
        return true;
    } catch (e) {
        console.error("Error decoding token:", e);
        return false;
    }
}

// Show or hide sections based on authentication
function toggleSections() {
    if (isAuthenticated()) {
        loginSection.classList.add("hidden");
        mainContent.classList.remove("hidden");
        addLogoutButton();
    } else {
        loginSection.classList.remove("hidden");
        mainContent.classList.add("hidden");
    }
}

toggleSections();

// Add logout button to main content
function addLogoutButton() {
    logoutButton.textContent = "Logout";
    logoutButton.classList.add("logout-button");
    logoutButton.addEventListener("click", logout);
    if (!document.body.contains(logoutButton)) {
        mainContent.prepend(logoutButton);
    }
}

// Logout functionality
function logout() {
    localStorage.removeItem("accessToken");
    toggleSections();
}

// Handle Login Form Submission
if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        const username = document.getElementById("username").value;
        const password = document.getElementById("password").value;

        try {
            const response = await fetch("0.0.0.0:8000/token/", {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: new URLSearchParams({ username, password }),
            });

            if (!response.ok) {
                if (response.status === 401) {
                    throw new Error("Invalid username or password.");
                } else {
                    throw new Error("An unexpected error occurred during login.");
                }
            }

            const result = await response.json();
            localStorage.setItem("accessToken", result.access_token); // Store token in localStorage

            toggleSections();
        } catch (error) {
            console.error(error);
            loginError.textContent = error.message;
            loginError.classList.remove("hidden");
        }
    });
}

// Update file status when a file is selected
if (document.getElementById("fileInput")) {
    document.getElementById("fileInput").addEventListener("change", (event) => {
        const file = event.target.files[0];

        if (file) {
            // Display the selected file name
            fileStatus.textContent = `Selected file: ${file.name}`;
            fileStatus.style.color = "#333"; // Change color to indicate success
        } else {
            // Reset if no file is selected
            fileStatus.textContent = "No file selected";
            fileStatus.style.color = "#666"; // Default color
        }
    });
}

// Handle Question Form Submission
if (questionForm) {
    questionForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        const fileInput = document.getElementById("fileInput");
        const questionInput = document.getElementById("questionInput");

        // Ensure file and question are provided
        if (!fileInput.files.length || !questionInput.value) {
            alert("Please upload a file and enter a question.");
            return;
        }

        // Show a loading message while processing
        responseSection.innerHTML = `<p>Loading...</p>`;

        const formData = new FormData();
        formData.append("file", fileInput.files[0]);
        formData.append("question", questionInput.value);

        const token = localStorage.getItem("accessToken");

        try {
            const response = await fetch("0.0.0.0:8000/ask/", {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${token}`,
                },
                body: formData,
            });

            if (!response.ok) {
                if (response.status === 401) {
                    throw new Error("Unauthorized. Please log in again.");
                } else {
                    throw new Error("An unexpected error occurred while fetching the answer.");
                }
            }

            const result = await response.json();

            // Display the enhanced response
            responseSection.innerHTML = `
                <div class="response-container">
                    <h3>Response for <span>${fileInput.files[0].name}</span></h3>
                    <p><strong>Question:</strong> ${questionInput.value}</p>
                    <h4>Answer</h4>
                    <p class="highlighted-answer">${result.answer}</p>
                    <h4>Explanation</h4>
                    <div class="explanation-box">${result.explanation}</div>
                </div>
            `;
        } catch (error) {
            // Handle fetch or network errors
            console.error("Error:", error);
            responseSection.innerHTML = `
                <p style="color: red;">${error.message}</p>
            `;
        }
    });
}

// Google Login Button
document.getElementById("googleLoginButton").addEventListener("click", async () => {
    try {
        // Fetch the Google login URL from the backend
        const response = await fetch("0.0.0.0:8000/google-login/");
        const data = await response.json();

        if (data.url) {
            // Redirect the user to Google's login page
            window.location.href = data.url;
        } else {
            alert("Failed to initiate Google login.");
        }
    } catch (error) {
        console.error("Error initiating Google login:", error);
        alert("An error occurred. Please try again.");
    }
});

// Store the token after Google login
function handleGoogleLoginCallback(accessToken) {
    if (accessToken) {
        localStorage.setItem("token", accessToken);
        alert("Google login successful!");
        window.location.reload(); // Refresh to load user-specific content
    } else {
        alert("Failed to log in with Google.");
    }
}

// Check if redirected back with a token
if (window.location.search.includes("access_token")) {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("access_token");
    handleGoogleLoginCallback(token);
}

// Check if redirected back with a token
if (window.location.search.includes("access_token")) {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("access_token");

    if (token) {
        localStorage.setItem("token", token);
        alert("Google login successful!");
        window.location.href = "/"; // Redirect to the home page or dashboard
    } else {
        alert("Google login failed. Please try again.");
    }
}

document.getElementById("logoutButton").addEventListener("click", () => {
    localStorage.removeItem("token");
    alert("You have been logged out.");
    window.location.href = "/";
});
