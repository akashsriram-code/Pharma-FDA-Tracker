/**
 * FDA Catalyst Tracker - Frontend JavaScript
 * Handles tab navigation, data filtering, and monthly grouping
 */

document.addEventListener('DOMContentLoaded', function () {
    // DOM Elements
    const eventsContainer = document.getElementById('events-container');
    const emptyState = document.getElementById('empty-state');
    const downloadBtn = document.getElementById('downloadBtn');
    const tabBtns = document.querySelectorAll('.tab-btn');
    const lastUpdatedEl = document.getElementById('lastUpdated');

    // State
    let globalData = [];
    let currentTab = 'all';

    // Fetch and render data
    fetch('data/data.json')
        .then(response => {
            if (!response.ok) {
                if (response.status === 404) return [];
                throw new Error("Network response was not ok");
            }
            return response.json();
        })
        .then(data => {
            globalData = data;
            updateCounts(data);
            updateStats(data);
            renderData(data, currentTab);
            updateLastUpdated();
        })
        .catch(error => {
            console.error('Error fetching data:', error);
            showEmptyState('Error loading data. Please try again later.');
        });

    // Tab switching
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTab = btn.dataset.tab;
            renderData(globalData, currentTab);
        });
    });

    // CSV Download
    downloadBtn.addEventListener('click', () => {
        if (!globalData.length) return alert("No data to download");
        downloadCSV(globalData);
    });

    /**
     * Categorize event by type
     */
    function categorizeEvent(item) {
        const type = (item.type || '').toLowerCase();
        const title = (item.title || '').toLowerCase();
        const source = (item.source || '').toLowerCase();

        if (type.includes('pdufa') || title.includes('pdufa') || type.includes('fda decision')) {
            return 'pdufa';
        }
        if (type.includes('adcomm') || type.includes('advisory') || title.includes('advisory committee')) {
            return 'adcomm';
        }
        if (type.includes('phase') || type.includes('trial') || source.includes('clinicaltrials')) {
            return 'trial';
        }
        if (type.includes('approval') || type.includes('approved')) {
            return 'approval';
        }
        if (type.includes('label') || type.includes('boxed warning')) {
            return 'label';
        }
        return 'pdufa'; // Default
    }

    /**
     * Filter data by tab
     */
    function filterByTab(data, tab) {
        if (tab === 'all') return data;

        return data.filter(item => {
            const category = categorizeEvent(item);
            if (tab === 'pdufa') return category === 'pdufa' || category === 'approval';
            if (tab === 'adcomm') return category === 'adcomm';
            if (tab === 'trials') return category === 'trial';
            if (tab === 'labels') return category === 'label';
            return true;
        });
    }

    /**
     * Group events by month
     */
    function groupByMonth(data) {
        const groups = {};
        const today = new Date();

        // Sort by date first
        const sorted = [...data].sort((a, b) => {
            const dateA = new Date(a.date);
            const dateB = new Date(b.date);
            if (isNaN(dateA)) return 1;
            if (isNaN(dateB)) return -1;
            return dateA - dateB;
        });

        sorted.forEach(item => {
            if (!item.date) return;

            const date = new Date(item.date);
            if (isNaN(date)) return;

            // Only show future and recent past (last 30 days), UNLESS it's a label update
            const daysDiff = (date - today) / (1000 * 60 * 60 * 24);
            const isLabel = categorizeEvent(item) === 'label';

            if (daysDiff < -30 && !isLabel) return;

            const monthKey = date.toLocaleDateString('en-US', { year: 'numeric', month: 'long' });

            if (!groups[monthKey]) {
                groups[monthKey] = [];
            }
            groups[monthKey].push(item);
        });

        return groups;
    }

    /**
     * Update tab counts
     */
    function updateCounts(data) {
        const counts = { all: 0, pdufa: 0, adcomm: 0, trials: 0, labels: 0 };
        const today = new Date();

        data.forEach(item => {
            if (!item.date) return;
            const date = new Date(item.date);
            if (isNaN(date)) return;

            // Only show future and recent past (last 30 days), UNLESS it's a label update
            const daysDiff = (date - today) / (1000 * 60 * 60 * 24);
            const isLabel = categorizeEvent(item) === 'label';

            if (daysDiff < -30 && !isLabel) return;

            // Only count future events or recent past for labels (labels are usually past events)
            // Actually, labels are "updates" so they are past events, but we want to show them.
            // Let's count them if they are in the dataset (which is already filtered to recent by scraper)
            if (date >= today || categorizeEvent(item) === 'label') {

                // Special logic: The scraper only saves future/recent events.
                // The frontend 'date >= today' logic hides past PDUFAs.
                // But Label updates are technically "past" actions.
                // We should show them if they are in the file.

                const category = categorizeEvent(item);

                if (date >= today || category === 'label') {
                    counts.all++;
                    if (category === 'pdufa' || category === 'approval') counts.pdufa++;
                    if (category === 'adcomm') counts.adcomm++;
                    if (category === 'trial') counts.trials++;
                    if (category === 'label') counts.labels++;
                }
            }
        });

        document.getElementById('count-all').textContent = counts.all;
        document.getElementById('count-pdufa').textContent = counts.pdufa;
        document.getElementById('count-adcomm').textContent = counts.adcomm;
        document.getElementById('count-trials').textContent = counts.trials;
        document.getElementById('count-labels').textContent = counts.labels;
    }

    /**
     * Render data grouped by month
     */
    function renderData(data, tab) {
        const filtered = filterByTab(data, tab);
        const grouped = groupByMonth(filtered);

        eventsContainer.innerHTML = '';

        const months = Object.keys(grouped);

        if (months.length === 0) {
            showEmptyState('No events found for this category.');
            return;
        }

        hideEmptyState();

        months.forEach(month => {
            const events = grouped[month];
            const groupEl = createMonthGroup(month, events);
            eventsContainer.appendChild(groupEl);
        });
    }

    /**
     * Create monthly group element
     */
    function createMonthGroup(month, events) {
        const group = document.createElement('div');
        group.className = 'month-group';

        group.innerHTML = `
            <div class="month-header">
                <span class="month-title">${month}</span>
                <span class="month-count">${events.length} event${events.length !== 1 ? 's' : ''}</span>
            </div>
            <div class="month-events"></div>
        `;

        const eventsContainer = group.querySelector('.month-events');

        events.forEach(item => {
            const card = createEventCard(item);
            eventsContainer.appendChild(card);
        });

        return group;
    }

    /**
     * Create event card element
     */
    function createEventCard(item) {
        const category = categorizeEvent(item);
        const card = document.createElement('div');
        card.className = `event-card ${category}`;

        // Format date nicely
        let dateDisplay = item.date || 'TBD';
        try {
            const d = new Date(item.date);
            if (!isNaN(d)) {
                dateDisplay = d.toLocaleDateString('en-US', {
                    weekday: 'short',
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric'
                });
            }
        } catch (e) { }

        // Get display type
        const typeLabel = getTypeLabel(item.type, category);

        card.innerHTML = `
            <div class="event-header">
                <span class="event-date">${dateDisplay}</span>
                <span class="event-type ${category}">${typeLabel}</span>
            </div>
            <div class="event-company">${item.company || 'Unknown'}</div>
            ${item.drug && item.drug !== 'N/A' && item.drug !== 'Check Filing' && item.drug !== 'Check Source'
                ? `<div class="event-drug">${item.drug}</div>`
                : ''}
            ${item.title
                ? `<div class="event-title">${truncate(item.title, 80)}</div>`
                : ''}
            ${item.link
                ? `<a href="${item.link}" target="_blank" rel="noopener" class="event-link">View Source →</a>`
                : ''}
        `;

        return card;
    }

    /**
     * Get display label for event type
     */
    function getTypeLabel(type, category) {
        if (!type) {
            const labels = { pdufa: 'PDUFA', adcomm: 'AdComm', trial: 'Trial', approval: 'Approval', label: 'Label Update' };
            return labels[category] || 'Event';
        }

        // Shorten long type names
        const t = type.toLowerCase();
        if (t.includes('pdufa')) return 'PDUFA';
        if (t.includes('adcomm') || t.includes('advisory')) return 'AdComm';
        if (t.includes('phase 3')) return 'Phase 3';
        if (t.includes('phase 4')) return 'Phase 4';
        if (t.includes('approval')) return 'Approval';
        if (t.includes('trial')) return 'Trial';
        if (t.includes('label') || t.includes('boxed')) return 'Label Update';

        return type.length > 15 ? type.substring(0, 12) + '...' : type;
    }

    /**
     * Truncate text
     */
    function truncate(text, maxLength) {
        if (!text || text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    /**
     * Show empty state
     */
    function showEmptyState(message) {
        eventsContainer.innerHTML = '';
        emptyState.classList.remove('hidden');
        if (message) {
            emptyState.querySelector('p').textContent = message;
        }
    }

    /**
     * Hide empty state
     */
    function hideEmptyState() {
        emptyState.classList.add('hidden');
    }

    /**
     * Update last updated text
     */
    function updateLastUpdated() {
        const now = new Date();
        lastUpdatedEl.textContent = `Updated ${now.toLocaleDateString()}`;
    }

    /**
     * Download data as CSV
     */
    function downloadCSV(data) {
        const headers = ["Company", "Drug", "Type", "Date", "Title", "Link", "Source"];
        const csvContent = [
            headers.join(','),
            ...data.map(row => headers.map(fieldName => {
                let cell = row[fieldName.toLowerCase()] || '';
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
    }
});
