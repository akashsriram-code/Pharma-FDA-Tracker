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
    let currentTab = 'pdufa';

    // Fetch and render data
    // Add a cache-buster to ensure we always get the latest data.json
    const cacheBuster = `?t=${new Date().getTime()}`;
    fetch(`data/data.json${cacheBuster}`)
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
        if (type.includes('shortage')) {
            return 'shortage';
        }
        return 'pdufa'; // Default
    }

    /**
     * Filter data by tab
     */
    function filterByTab(data, tab) {

        return data.filter(item => {
            const category = categorizeEvent(item);
            if (tab === 'pdufa') return category === 'pdufa' || category === 'approval';
            if (tab === 'adcomm') return category === 'adcomm';
            if (tab === 'trials') return category === 'trial';
            if (tab === 'labels') return category === 'label';
            if (tab === 'shortages') return category === 'shortage';
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
        const counts = { pdufa: 0, adcomm: 0, trials: 0, labels: 0, shortages: 0 };
        const today = new Date();

        data.forEach(item => {
            if (!item.date) return;
            const date = new Date(item.date);
            if (isNaN(date)) return;

            // Only show future and recent past (last 30 days), UNLESS it's a label update or shortage
            const daysDiff = (date - today) / (1000 * 60 * 60 * 24);
            const isLabelOrShortage = categorizeEvent(item) === 'label' || categorizeEvent(item) === 'shortage';

            if (daysDiff < -30 && !isLabelOrShortage) return;

            // Only count future events or recent past for labels (labels are usually past events)
            // Actually, labels are "updates" so they are past events, but we want to show them.
            // Let's count them if they are in the dataset (which is already filtered to recent by scraper)
            if (date >= today || categorizeEvent(item) === 'label') {

                // Special logic: The scraper only saves future/recent events.
                // The frontend 'date >= today' logic hides past PDUFAs.
                // But Label updates are technically "past" actions.
                // We should show them if they are in the file.

                const category = categorizeEvent(item);

                if (date >= today || category === 'label' || category === 'shortage') {

                    if (category === 'pdufa' || category === 'approval') counts.pdufa++;
                    if (category === 'adcomm') counts.adcomm++;
                    if (category === 'trial') counts.trials++;
                    if (category === 'label') counts.labels++;
                    if (category === 'shortage') counts.shortages++;
                }
            }
        });


        document.getElementById('count-pdufa').textContent = counts.pdufa;
        document.getElementById('count-adcomm').textContent = counts.adcomm;
        document.getElementById('count-trials').textContent = counts.trials;
        document.getElementById('count-labels').textContent = counts.labels;
        const countShortagesEl = document.getElementById('count-shortages');
        if (countShortagesEl) countShortagesEl.textContent = counts.shortages;
    }


    /**
     * Render data grouped by month
     */
    function renderData(data, tab) {
        const filtered = filterByTab(data, tab);
        const displayData = tab === 'shortages'
            ? filtered
            : filterCurrentMonthForward(filtered);

        eventsContainer.innerHTML = '';

        if (displayData.length === 0) {
            showEmptyState('No events found for this category.');
            return;
        }

        hideEmptyState();

        // Special Layout for Label Changes
        if (tab === 'labels') {
            renderLabelList(displayData);
            return;
        }

        // Special Layout for Drug Shortages
        if (tab === 'shortages') {
            renderShortageList(displayData);
            return;
        }

        // Standard Monthly Grouping for other tabs
        const grouped = groupByMonth(displayData);
        const months = Object.keys(grouped);

        months.forEach(month => {
            const events = grouped[month];
            const groupEl = createMonthGroup(month, events);
            eventsContainer.appendChild(groupEl);
        });
    }

    /**
     * Keep only events from current month and forward for display.
     */
    function filterCurrentMonthForward(data) {
        if (!data || !data.length) return [];

        const now = new Date();
        const firstDayOfCurrentMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        firstDayOfCurrentMonth.setHours(0, 0, 0, 0);

        return data.filter(item => {
            if (!item || !item.date) return false;
            const d = new Date(item.date);
            if (isNaN(d)) return false;
            return d >= firstDayOfCurrentMonth;
        });
    }

    /**
     * Render Label Changes List (Reverse Chronological)
     */
    function renderLabelList(data) {
        // Sort by date descending
        const sorted = [...data].sort((a, b) => {
            return new Date(b.date) - new Date(a.date);
        });

        sorted.forEach(item => {
            const card = createLabelCard(item);
            eventsContainer.appendChild(card);
        });
    }

    /**
     * Create Label Change Card (Expandable)
     */
    function createLabelCard(item) {
        const card = document.createElement('div');
        card.className = 'event-card label expandable';

        let dateDisplay = item.date || 'TBD';
        try {
            const d = new Date(item.date);
            if (!isNaN(d)) dateDisplay = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        } catch (e) { }

        const title = item.title ? item.title.replace('Label Update:', '').trim() : 'Label Update';
        const hasDiff = item.diff_data && item.diff_data.sections && item.diff_data.sections.length > 0;

        card.innerHTML = `
            <div class="event-header">
                <span class="event-date">${dateDisplay}</span>
                <span class="event-type label">Label Update</span>
            </div>
            <div class="event-company">${item.company}</div>
            <div class="event-drug">${item.drug}</div>
            <div class="event-title">${truncate(title, 100)}</div>
            ${hasDiff ? '<span class="diff-badge">DIFF AVAILABLE</span>' : ''}
            
            <div class="label-details hidden">
                ${hasDiff ? renderDiffData(item.diff_data) : ''}
                <div class="diff-view">
                    <div class="diff-header">${hasDiff ? 'Section Details (from OpenFDA)' : 'Change Details'}</div>
                    <div class="diff-content">
                        ${formatDiffContent(item.details)}
                    </div>
                </div>
                <a href="${item.link}" target="_blank" class="event-link" onclick="event.stopPropagation()">View Full Label on DailyMed →</a>
            </div>
        `;

        // Toggle Expand
        card.addEventListener('click', (e) => {
            // Don't toggle when clicking on collapsible section headers
            if (e.target.closest('.diff-section-toggle')) return;
            card.classList.toggle('expanded');
            const details = card.querySelector('.label-details');
            details.classList.toggle('hidden');
        });

        // Set up collapsible section toggles after adding to DOM
        setTimeout(() => {
            card.querySelectorAll('.diff-section-toggle').forEach(toggle => {
                toggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const body = toggle.nextElementSibling;
                    const arrow = toggle.querySelector('.toggle-arrow');
                    if (body) {
                        body.classList.toggle('collapsed');
                        if (arrow) {
                            arrow.textContent = body.classList.contains('collapsed') ? '▶' : '▼';
                        }
                    }
                });
            });
        }, 0);

        return card;
    }

    /**
     * Render the DailyMed archive diff (new diff_data format)
     */
    function renderDiffData(diffData) {
        if (!diffData || !diffData.sections) return '';

        let html = '<div class="archive-diff">';

        // Version header
        html += `<div class="diff-version-header">
            <span class="diff-version-badge old">v${diffData.previous_version}</span>
            <span class="diff-version-date">${diffData.previous_date || ''}</span>
            <span class="diff-version-arrow">→</span>
            <span class="diff-version-badge new">v${diffData.current_version}</span>
            <span class="diff-version-date">${diffData.current_date || ''}</span>
        </div>`;

        // Each section
        diffData.sections.forEach(section => {
            const addedBadge = section.added_count > 0
                ? `<span class="change-count added">+${section.added_count}</span>` : '';
            const removedBadge = section.removed_count > 0
                ? `<span class="change-count removed">-${section.removed_count}</span>` : '';

            html += `<div class="diff-section-wrapper">
                <div class="diff-section-toggle">
                    <span class="toggle-arrow">▼</span>
                    <span class="diff-section-name">${escapeHtml(section.section)}</span>
                    ${addedBadge}${removedBadge}
                </div>
                <div class="diff-section-body">`;

            if (section.diff_lines && section.diff_lines.length > 0) {
                html += '<div class="diff-lines">';
                section.diff_lines.forEach(line => {
                    const prefix = line.type === 'added' ? '+ ' : line.type === 'removed' ? '- ' : '  ';
                    html += `<div class="diff-line diff-line-${line.type}">`
                        + `<span class="diff-line-prefix">${prefix}</span>`
                        + `<span class="diff-line-text">${escapeHtml(line.text)}</span>`
                        + `</div>`;
                });
                html += '</div>';
            }

            html += '</div></div>';
        });

        html += '</div>';
        return html;
    }

    /**
     * Escape HTML entities for safe rendering
     */
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Format Diff Content (legacy details field)
     */
    function formatDiffContent(details) {
        if (!details) return '<span class="text-muted">No details available.</span>';

        try {
            const structuredData = JSON.parse(details);
            if (Array.isArray(structuredData)) {
                let html = '<div class="diff-summary">';

                html += '<table class="diff-table">';
                html += '<thead><tr><th>Section</th><th>Subsection</th><th>Date</th></tr></thead>';
                html += '<tbody>';
                structuredData.forEach(item => {
                    html += `<tr>
                        <td>${item.section}</td>
                        <td>${item.subsection}</td>
                        <td>${item.date}</td>
                    </tr>`;
                });
                html += '</tbody></table></div>';

                return html;
            }
        } catch (e) {
            console.log("Legacy details format:", e);
        }

        return details.replace(/\n/g, '<br>')
            .replace(/(Section:)/g, '<span class="diff-section-label">$1</span>');
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

    /**
     * Render Drug Shortages List (Reverse Chronological)
     */
    function renderShortageList(data) {
        // Sort by date descending
        const sorted = [...data].sort((a, b) => {
            return new Date(b.date) - new Date(a.date);
        });

        sorted.forEach(item => {
            const card = createShortageCard(item);
            eventsContainer.appendChild(card);
        });
    }

    /**
     * Create Drug Shortage Card
     */
    function createShortageCard(item) {
        const card = document.createElement('div');
        card.className = 'event-card shortage';

        let dateDisplay = item.date || 'TBD';
        try {
            const d = new Date(item.date);
            if (!isNaN(d)) dateDisplay = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        } catch (e) { }

        card.innerHTML = `
            <div class="event-header">
                <span class="event-date">${dateDisplay}</span>
                <span class="event-type trial" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border-color: rgba(239, 68, 68, 0.3);">FDA Shortage</span>
            </div>
            <div class="event-company">${item.company}</div>
            <div class="event-drug">${item.drug}</div>
            <div class="event-title">${item.title}</div>
            <div class="event-details" style="margin-top: 12px; font-size: 0.9rem; color: var(--text-secondary); background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px;">
                ${item.details || 'Reason: Not specified'}
            </div>
            <div style="margin-top: 12px;">
                <a href="${item.link}" target="_blank" class="event-link" onclick="event.stopPropagation()">View Details on FDA Website →</a>
            </div>
        `;

        return card;
    }

});
