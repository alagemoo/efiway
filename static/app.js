// Updated app.js with support for bullet points in suggestions

// Update file status when a file is selected
document.getElementById("fileInput").addEventListener("change", (event) => {
    const fileStatus = document.getElementById("fileStatus");
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

// Handle the "Get Answer" button click
document.getElementById("generateAnswer").addEventListener("click", async (e) => {
    e.preventDefault();

    const fileInput = document.getElementById("fileInput");
    const questionInput = document.getElementById("questionInput");
    const responseSection = document.getElementById("responseSection");

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

    try {
        const response = await fetch("http://127.0.0.1:8200/ask/", {
            method: "POST",
            body: formData,
        });

        if (!response.ok) {
            throw new Error(`HTTP error! Status: ${response.status}`);
        }

        const result = await response.json();

        // Check if the backend returned an error
        if (result.error) {
            responseSection.innerHTML = `<p style="color: red;">${result.error}</p>`;
            console.error("Backend error:", result.error);
            return;
        }

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
            <p style="color: red;">An error occurred. Please try again.</p>
        `;
    }
});
