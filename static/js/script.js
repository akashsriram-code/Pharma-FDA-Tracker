document.addEventListener('DOMContentLoaded', function () {
    const listEl = document.getElementById('catalyst-list');
    const downloadBtn = document.getElementById('downloadBtn');

    let globalData = [];

    // Fetch Data
    fetch('data/data.json')
        .then(response => {
            if (!response.ok) {
                if (response.status === 404) return []; // Handle empty state
                throw new Error("Network response was not ok");
            }
            return response.json();
        })
        .then(data => {
            globalData = data;
            renderData(data);
        })
        .catch(error => {
            console.error('Error fetching data:', error);
            listEl.innerHTML = '<p>No data found or error loading data. Run the scraper first.</p>';
        });

    function renderData(data) {
        // Render List
        listEl.innerHTML = '';

        if (data.length === 0) {
            listEl.innerHTML = '<p>No upcoming events found.</p>';
            return;
        }

        // Sort by date if possible
        const sortedData = [...data].sort((a, b) => {
            const dateA = new Date(a.date);
            const dateB = new Date(b.date);
            if (isNaN(dateA)) return 1;
            if (isNaN(dateB)) return -1;
            return dateA - dateB;
        });

        sortedData.forEach(item => {
            const card = document.createElement('div');
            card.className = `catalyst-card ${item.type.toLowerCase().includes('adcomm') ? 'adcomm' : 'pdufa'}`;

            card.innerHTML = `
                <div class="card-header">
                    <span>${item.date}</span>
                    <span>${item.type}</span>
                </div>
                <div class="card-title">${item.company}</div>
                ${item.drug !== 'N/A' ? `<div class="card-drug">${item.drug}</div>` : ''}
                <div style="margin-top:10px; font-size:0.9em;">
                    <a href="${item.link}" target="_blank" style="color:var(--accent-blue); text-decoration:none;">View Source &rarr;</a>
                </div>
            `;
            listEl.appendChild(card);
        });
    }

    downloadBtn.addEventListener('click', () => {
        if (!globalData.length) return alert("No data to download");

        const headers = ["Company", "Drug", "Type", "Date", "Title", "Link", "Source"];
        const csvContent = [
            headers.join(','),
            ...globalData.map(row => headers.map(fieldName => {
                let cell = row[fieldName.toLowerCase()] || '';
                // Escape commas
                return `"${String(cell).replace(/"/g, '""')}"`;
            }).join(','))
        ].join('\n');

        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.setAttribute("href", url);
        link.setAttribute("download", "fda_catalysts.csv");
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    });
});
