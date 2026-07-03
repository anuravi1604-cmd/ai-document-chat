
        const API_BASE = `${window.location.origin}/api`;
        let files = [];
        let activeFileId = null;
        let isGenerating = false;
        let currentSources = [];
        let autoOpenOnUpload = localStorage.getItem("autoOpenOnUpload") === "true";
        let currentChatController = null;

        // DOM Elements
        const dropZone = document.getElementById("drop-zone");
        const fileInput = document.getElementById("file-input");
        const filesList = document.getElementById("files-list");
        const fileCount = document.getElementById("file-count");
        const searchFiles = document.getElementById("search-files");

        const chatHeader = document.getElementById("chat-header");
        const activeFileIcon = document.getElementById("active-file-icon");
        const activeFileTitle = document.getElementById("active-file-title");
        const activeFileSize = document.getElementById("active-file-size");
        const chatFeed = document.getElementById("chat-feed");
        const blankSlate = document.getElementById("blank-slate");
        const chatInputBar = document.getElementById("chat-input-bar");
        const chatForm = document.getElementById("chat-form");
        const userInput = document.getElementById("user-input");
        const btnSend = document.getElementById("btn-send");
        const btnStop = document.getElementById("btn-stop");

        btnStop.addEventListener("click", () => {
            if (currentChatController) {
                currentChatController.abort();
            }
        });
        const btnExportChat = document.getElementById("btn-export-chat");
        const btnClearChat = document.getElementById("btn-clear-chat");
        const btnDeleteFile = document.getElementById("btn-delete-file");

        // Citations Panel Elements
        const citationsSidebar = document.getElementById("citations-sidebar");
        const citationsSidebarContent = document.getElementById("citations-sidebar-content");
        const btnCloseCitations = document.getElementById("btn-close-citations");

        // Resizable Sidebars State & Logic
        let lastLeftWidth = 320;
        let lastRightWidth = 384;
        let leftCollapsed = false;
        let rightCollapsed = false;

        function initSidebarResizers() {
            const leftSidebar = document.getElementById("left-sidebar");
            const leftResizer = document.getElementById("left-resizer");
            const leftCollapseBtn = document.getElementById("left-collapse-btn");

            const rightSidebar = document.getElementById("citations-sidebar");
            const rightResizer = document.getElementById("right-resizer");
            const rightCollapseBtn = document.getElementById("right-collapse-btn");

            let isLeftResizing = false;
            let isRightResizing = false;

            // Left Handle Drag mousedown
            leftResizer.addEventListener("mousedown", (e) => {
                if (e.target === leftCollapseBtn || leftCollapseBtn.contains(e.target)) return;
                isLeftResizing = true;
                document.body.style.cursor = "col-resize";
                document.body.style.userSelect = "none";
            });

            // Right Handle Drag mousedown
            rightResizer.addEventListener("mousedown", (e) => {
                if (e.target === rightCollapseBtn || rightCollapseBtn.contains(e.target)) return;
                isRightResizing = true;
                document.body.style.cursor = "col-resize";
                document.body.style.userSelect = "none";
            });

            // Drag mousemove handler
            document.addEventListener("mousemove", (e) => {
                if (isLeftResizing) {
                    const newWidth = Math.max(200, Math.min(480, e.clientX));
                    lastLeftWidth = newWidth;
                    leftSidebar.style.width = `${newWidth}px`;
                    leftResizer.style.left = `${newWidth}px`;
                    leftCollapsed = false;
                    leftSidebar.classList.remove("collapsed");
                    updateResizerChevrons();
                }
                if (isRightResizing) {
                    const wrapperWidth = document.body.clientWidth;
                    const newWidth = Math.max(280, Math.min(600, wrapperWidth - e.clientX));
                    lastRightWidth = newWidth;
                    rightSidebar.style.width = `${newWidth}px`;
                    rightResizer.style.right = `${newWidth}px`;
                    rightCollapsed = false;
                    rightSidebar.classList.remove("collapsed");
                    updateResizerChevrons();
                }
            });

            // Mouseup reset handler
            document.addEventListener("mouseup", () => {
                if (isLeftResizing || isRightResizing) {
                    isLeftResizing = false;
                    isRightResizing = false;
                    document.body.style.cursor = "default";
                    document.body.style.userSelect = "auto";
                }
            });

            // Click collapse arrow Left
            leftCollapseBtn.addEventListener("click", () => {
                leftCollapsed = !leftCollapsed;
                if (leftCollapsed) {
                    leftSidebar.style.width = "0px";
                    leftResizer.style.left = "0px";
                    leftSidebar.classList.add("collapsed");
                } else {
                    leftSidebar.style.width = `${lastLeftWidth}px`;
                    leftResizer.style.left = `${lastLeftWidth}px`;
                    leftSidebar.classList.remove("collapsed");
                }
                updateResizerChevrons();
            });

            // Click collapse arrow Right
            rightCollapseBtn.addEventListener("click", () => {
                rightCollapsed = !rightCollapsed;
                if (rightCollapsed) {
                    rightSidebar.style.width = "0px";
                    rightResizer.style.right = "0px";
                    rightSidebar.classList.add("collapsed");
                } else {
                    rightSidebar.style.width = `${lastRightWidth}px`;
                    rightResizer.style.right = `${lastRightWidth}px`;
                    rightSidebar.classList.remove("collapsed");
                }
                updateResizerChevrons();
            });

            function updateResizerChevrons() {
                leftCollapseBtn.innerHTML = leftCollapsed 
                    ? `<i data-lucide="chevron-right" class="h-3.5 w-3.5"></i>` 
                    : `<i data-lucide="chevron-left" class="h-3.5 w-3.5"></i>`;
                
                rightCollapseBtn.innerHTML = rightCollapsed 
                    ? `<i data-lucide="chevron-left" class="h-3.5 w-3.5"></i>` 
                    : `<i data-lucide="chevron-right" class="h-3.5 w-3.5"></i>`;
                
                lucide.createIcons();
            }
            
            window.updateResizerChevrons = updateResizerChevrons;
        }

        // Initialize
        document.addEventListener("DOMContentLoaded", () => {
            fetchFiles().then(() => {
                setTimeout(() => {
                    const activeType = localStorage.getItem('contextiq_active_type');
                    const activeId = localStorage.getItem('contextiq_active_id');
                    if (activeType === 'collection' && activeId) {
                        const tab = document.getElementById('tab-collections');
                        if(tab) tab.click();
                        if (typeof selectCollection === 'function') selectCollection(activeId);
                    } else if (activeType === 'file' && activeId) {
                        const tab = document.getElementById('tab-documents');
                        if(tab) tab.click();
                        selectWorkspace(activeId, 'ready');
                    }
                }, 200);
            });
            initDragAndDrop();
            initTextareaAutoGrow();
            initSidebarResizers();

            // Initialize Auto-Open Toggle
            const autoOpenToggle = document.getElementById("auto-open-toggle");
            if (autoOpenToggle) {
                autoOpenToggle.checked = autoOpenOnUpload;
                autoOpenToggle.addEventListener("change", (e) => {
                    localStorage.setItem("autoOpenOnUpload", e.target.checked);
                    autoOpenOnUpload = e.target.checked;
                });
            }

            // Close Citations Sidebar
            if (btnCloseCitations) {
                btnCloseCitations.addEventListener("click", () => {
                    citationsSidebar.classList.add("hidden");
                    document.getElementById("right-resizer").classList.add("hidden");
                });
            }

            // Handle LLM Provider selector changes
            const llmProvider = document.getElementById("llm-provider");



            // Periodically refresh list of processing files
            setInterval(pollProcessingFiles, 4000);
        });

        // Icon Utility
        const fileIconMap = {
            "pdf": "file-text",
            "docx": "file-word",
            "txt": "file-edit"
        };

        function getFileIcon(type) {
            if (type === "pdf") {
                return `<i data-lucide="file-text" class="h-4.5 w-4.5 text-rose-400"></i>`;
            }

            if (type === "docx") {
                return `<i data-lucide="file-text" class="h-4.5 w-4.5 text-blue-400"></i>`;
            }

            if (type === "txt") {
                return `<i data-lucide="file-edit" class="h-4.5 w-4.5 text-gray-300"></i>`;
            }

            if (type === "csv" || type === "excel") {
                return `<i data-lucide="table" class="h-4.5 w-4.5 text-emerald-400"></i>`;
            }

            return `<i data-lucide="file" class="h-4.5 w-4.5 text-gray-400"></i>`;
        }

        // Create a Toast Alert
        function showToast(title, message, type = "info") {
            const container = document.getElementById("toast-container");
            const toast = document.createElement("div");
            toast.className = `glass-panel p-4 rounded-xl shadow-xl flex items-start gap-3 border border-darkBorder/80 fade-in select-none`;

            let colorClass = "text-blue-400 bg-blue-500/10";
            let iconName = "info";
            if (type === "success") {
                colorClass = "text-emerald-400 bg-emerald-500/10";
                iconName = "check-circle-2";
            } else if (type === "error") {
                colorClass = "text-rose-400 bg-rose-500/10";
                iconName = "alert-circle";
            } else if (type === "warning") {
                colorClass = "text-amber-400 bg-amber-500/10";
                iconName = "alert-triangle";
            }

            toast.innerHTML = `
                <div class="h-8 w-8 rounded-lg ${colorClass} flex items-center justify-center shrink-0">
                    <i data-lucide="${iconName}" class="h-4.5 w-4.5"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <p class="text-xs font-bold text-white">${title}</p>
                    <p class="text-[10px] text-gray-400 mt-0.5 leading-relaxed">${message}</p>
                </div>
                <button class="text-gray-500 hover:text-gray-300 shrink-0 mt-0.5 transition" onclick="this.parentElement.remove()">
                    <i data-lucide="x" class="h-3.5 w-3.5"></i>
                </button>
            `;
            container.appendChild(toast);
            lucide.createIcons();

            // Auto remove after 5 seconds
            setTimeout(() => {
                toast.classList.add("opacity-0", "translate-y-2");
                toast.style.transition = "all 0.4s ease";
                setTimeout(() => toast.remove(), 400);
            }, 5000);
        }

        // Fetch all documents from API
        async function fetchFiles() {
            try {
                const response = await fetch(`${API_BASE}/files`);
                if (!response.ok) throw new Error("Could not load documents");
                files = await response.ok ? await response.json() : [];
                renderFilesList();
            } catch (err) {
                console.error(err);
                if (docModal) docModal.remove();
                showToast("Upload Error", err.message || "An error occurred while uploading.", "error");
            }
        }

        // Render Files List in Sidebar
        function renderFilesList() {
            const query = searchFiles.value.toLowerCase().trim();
            const filtered = files.filter(f => f.filename.toLowerCase().includes(query));

            fileCount.innerText = `${files.length} file${files.length !== 1 ? 's' : ''}`;

            if (filtered.length === 0) {
                filesList.innerHTML = `
                    <div class="text-center py-8 text-gray-500">
                        <i data-lucide="file-warning" class="h-8 w-8 mx-auto mb-2 text-gray-600"></i>
                        <p class="text-xs">${query ? 'No matching documents' : 'No documents uploaded'}</p>
                    </div>
                `;
                lucide.createIcons();
                return;
            }

            filesList.innerHTML = filtered.map(file => {
                const sizeKB = (file.file_size / 1024).toFixed(0);
                const sizeStr = sizeKB > 1024 ? `${(sizeKB / 1024).toFixed(1)} MB` : `${sizeKB} KB`;
                const isActive = file.id === activeFileId;

                let statusBadge = "";
                let itemClass = "hover:bg-darkPanel border border-transparent";
                let pointerClass = "cursor-pointer";

                if (file.status === "processing") {
                    statusBadge = `
                        <span class="flex items-center gap-1 text-[9px] font-semibold text-brand-400 bg-brand-500/10 px-2 py-0.5 rounded-full">
                            <span class="h-1.5 w-1.5 rounded-full bg-brand-400 animate-pulse"></span>
                            Indexing...
                        </span>`;
                    itemClass = "bg-darkPanel/20 border border-darkBorder/30 animate-pulse";
                    pointerClass = "cursor-not-allowed";
                } else if (file.status === "error") {
                    statusBadge = `<span class="text-[9px] font-semibold text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded-full flex items-center gap-1"><i data-lucide="x" class="h-2.5 w-2.5"></i> Failed</span>`;
                } else if (isActive) {
                    itemClass = "bg-gradient-to-tr from-brand-600/10 to-indigo-500/[0.03] border border-brand-500/25 shadow-lg shadow-brand-500/[0.02]";
                } else {
                    itemClass = "bg-darkPanel/40 hover:bg-darkPanel border border-darkBorder/40";
                }

                return `
                    <div onclick="selectWorkspace('${file.id}', '${file.status}')" 
                        draggable="true" ondragstart="window.setDraggedFileId(\'${file.id}\')" class="relative p-3.5 rounded-xl transition ${pointerClass} ${itemClass} flex items-start justify-between group cursor-grab active:cursor-grabbing">

                        <!-- ACTION BUTTONS (Visible on hover) -->
                        <div class="absolute top-2.5 right-2.5 flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition z-20">
                            <button 
                                onclick="event.stopPropagation(); quickDeleteFile('${file.id}')"
                                class="h-6 w-6 rounded bg-darkPanel border border-darkBorder/60 flex items-center justify-center text-gray-400 hover:text-red-400 hover:border-red-500/30 transition"
                                title="Delete Document"
                            >
                                <i data-lucide="trash-2" class="h-3.5 w-3.5"></i>
                            </button>
                        </div>

                        <div class="flex items-start gap-3 min-w-0">
                            <div class="h-8.5 w-8.5 rounded-lg bg-darkBorder group-hover:bg-darkBorder flex items-center justify-center shrink-0 text-gray-400 ${isActive ? 'text-brand-400 bg-brand-500/10 border border-brand-500/10' : ''}">
                                ${getFileIcon(file.file_type)}
                            </div>

                            <div class="min-w-0">
                                <p 
                                    class="text-xs font-semibold text-gray-200 truncate pr-8 group-hover:text-white transition cursor-pointer"
                                    title="Double-click to open original file"
                                    ondblclick="window.open('${API_BASE}/files/${file.id}/view', '_blank'); event.stopPropagation();"
                                >
                                    ${file.filename}
                                </p>

                            <div class="flex items-center gap-1.5 mt-1">
                                <span class="text-[9px] text-gray-500">${sizeStr}</span>
                                <span class="text-gray-700 text-[9px]">•</span>
                                <span class="text-[9px] text-gray-500">
                                    ${new Date(file.uploaded_at).toLocaleDateString()}
                                </span>
                            </div>
                            ${(file.status === "ready" && !["csv", "excel"].includes(file.file_type)) ? `
                                ${file.graph_ready 
                                    ? `<span class="flex items-center gap-1 text-[8px] font-semibold text-emerald-400/80 bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/10 mt-1.5 w-fit"><i data-lucide="network" class="h-2.5 w-2.5"></i> Graph Ready</span>` 
                                    : `<div class="mt-2 w-full max-w-[120px] bg-brand-500/10 rounded-full h-1.5 border border-brand-500/20 overflow-hidden relative" title="Building Knowledge Graph: ${file.graph_progress || 0}%">
                                           <div class="absolute inset-y-0 left-0 bg-brand-500 rounded-full transition-all duration-500 ease-out shadow-[0_0_8px_rgba(92,122,255,0.6)]" style="width: ${file.graph_progress || 0}%"></div>
                                       </div>`
                                }
                            ` : ''}
                        </div>
                    </div>
                </div>

                <div class="shrink-0 pl-2">
                    ${statusBadge}
                </div>
            </div>
        `;
            }).join("");

            lucide.createIcons();
        }

        // Active Search Filter
        searchFiles.addEventListener("input", renderFilesList);

        // Poll files that are indexing to check status
        async function pollProcessingFiles() {
            const hasProcessing = files.some(f => f.status === "processing" || (f.status === "ready" && !f.graph_ready && !["csv", "excel"].includes(f.file_type)));
            if (!hasProcessing) return;

            try {
                const response = await fetch(`${API_BASE}/files`);
                if (response.ok) {
                    const newFiles = await response.json();

                    // Check if any finished indexing to Toast it
                    newFiles.forEach(nf => {
                        const oldFile = files.find(of => of.id === nf.id);
                        if (oldFile && oldFile.status === "processing" && nf.status === "ready") {
                            showToast("Document Processed", `"${nf.filename}" has been successfully parsed, chunked, and embedded into vector db. Ready for workspace.<br><a href="${API_BASE}/files/${nf.id}/view" target="_blank" class="text-brand-400 hover:underline font-semibold block mt-1.5 flex items-center gap-1"><i data-lucide="external-link" class="h-3 w-3 inline"></i> Open Original File</a>`, "success");
                            if (activeFileId === nf.id) {
                                selectWorkspace(nf.id, "ready");
                            }
                        } else if (oldFile && oldFile.status === "processing" && nf.status === "error") {
                            showToast("Indexing Failed", `An error occurred during indexing for "${nf.filename}".`, "error");
                        } else if (oldFile && oldFile.status === "ready" && !oldFile.graph_ready && nf.graph_ready) {
                            showToast("Graph Ready", `Knowledge Graph generation finished for "${nf.filename}". Tri-brid retrieval is now fully active!`, "success");
                        }
                    });

                    files = newFiles;
                    renderFilesList();
                }
            } catch (err) {
                console.error("Polling error:", err);
            }
        }

        // Handle Active workspace Selection
        async function selectWorkspace(fileId, status) {
            if (currentChatController) {
                // We no longer abort the stream so background generation can finish
                currentChatController = null;
                isGenerating = false;
            }
            if (status === "error") {
                showToast("Indexing Failed", "This document indexing has failed. Please delete and upload it again.", "error");
                return;
            }

            activeFileId = fileId;
            localStorage.setItem('contextiq_active_type', 'file');
            localStorage.setItem('contextiq_active_id', fileId);
            citationsSidebar.classList.add("hidden");
            const rr1 = document.getElementById("right-resizer");
            if (rr1) rr1.classList.add("hidden");

            citationsSidebarContent.innerHTML = `
                <div class="text-center py-12 text-gray-500 select-none">
                    <i data-lucide="info" class="h-8 w-8 mx-auto mb-2 text-gray-600"></i>
                    <p class="text-xs text-gray-400 px-4">
                        No sources yet. Ask a question to retrieve grounded citations.
                    </p>
                </div>
            `;
            renderFilesList();

            const file = files.find(f => f.id === fileId);
            if (!file) return;

            // 1. Show main UI components
            blankSlate.classList.add("hidden");
            chatHeader.classList.remove("hidden");
            chatInputBar.classList.remove("hidden");
            document.getElementById("btn-delete-file").classList.remove("hidden");
            document.getElementById("btn-add-file-to-context").classList.remove("hidden");
            document.getElementById("btn-view-collection-files").classList.add("hidden");

            // 2. Load workspace metadata header
            const sizeKB = (file.file_size / 1024).toFixed(0);
            const sizeStr = sizeKB > 1024 ? `${(sizeKB / 1024).toFixed(1)} MB` : `${sizeKB} KB`;

            activeFileTitle.innerText = file.filename;
            activeFileTitle.setAttribute("ondblclick", `window.open('${API_BASE}/files/${file.id}/view', '_blank')`);
            activeFileTitle.classList.add("cursor-pointer", "hover:text-brand-300", "transition");
            activeFileTitle.setAttribute("title", "Double-click to open original file");
            
            activeFileSize.innerText = sizeStr;
            activeFileIcon.innerHTML = getFileIcon(file.file_type);
            lucide.createIcons();

            if (status === "processing") {
                // Render the indexing loader in the chatFeed
                toggleInputState(true, true);
                chatFeed.innerHTML = `
                    <div class="flex-grow flex flex-col items-center justify-center text-center max-w-lg mx-auto py-12 fade-in select-none">
                        <div class="h-12 w-12 rounded-xl bg-brand-600/10 border border-brand-500/15 flex items-center justify-center mb-4">
                            <span class="h-6 w-6 rounded-full border-2 border-brand-500/20 border-t-brand-500 animate-spin"></span>
                        </div>
                        <h4 class="text-sm font-semibold text-white">Indexing Document</h4>
                        <p class="text-gray-400 text-xs mt-2 leading-relaxed">
                            Parsing parsing layers, chunking content, and constructing vector embeddings for "${file.filename}".<br>
                            Workspace will automatically unlock once indexing completes.
                        </p>
                        <a href="${API_BASE}/files/${fileId}/view" target="_blank" class="px-4 py-2 mt-6 rounded-lg bg-darkPanel border border-darkBorder text-xs text-brand-400 hover:border-brand-500/30 transition flex items-center gap-1.5 font-semibold">
                            <i data-lucide="external-link" class="h-4 w-4"></i> Open Original Document
                        </a>
                    </div>
                `;
                lucide.createIcons();
                return;
            }

            // Otherwise, it is "ready"
            toggleInputState(false);

            // 3. Clear existing feed and load messages
            chatFeed.innerHTML = `
                <div class="flex-1 flex items-center justify-center py-12">
                    <span class="h-6 w-6 rounded-full border-2 border-brand-500/20 border-t-brand-500 animate-spin"></span>
                </div>
            `;

            try {
                const response = await fetch(`${API_BASE}/files/${fileId}/messages`);
                if (!response.ok) throw new Error("Could not load messages");
                const res = await response.json();

                chatFeed.innerHTML = "";

                if (res.messages.length === 0) {
                    renderEmptyChatState(file.filename);
                } else {
                    res.messages.forEach(msg => {
                        appendMessageBubble(msg.role, msg.content, msg.sources, false, msg.id);
                    });
                }
                if (window.activeGenerations[fileId]) {
                    const b = appendMessageBubble('assistant', '<div class="flex items-center gap-2 text-brand-400"><span class="h-2 w-2 rounded-full bg-brand-400 animate-pulse"></span> Generating response in background... Please wait.</div>', null, true);
                    const cd = b.querySelector('.message-content');
                    if(cd) cd.classList.remove('typing-cursor');
                }
                scrollToBottom();
            } catch (err) {
                console.error(err);
                showToast("Error", "Could not retrieve session history.", "error");
            }
        }

        window.renderEmptyChatState = renderEmptyChatState;
        function renderEmptyChatState(filename) {
            chatFeed.innerHTML = `
                <div id="empty-state-isolated" class="flex-grow flex flex-col items-center justify-center text-center max-w-lg mx-auto py-12 fade-in select-none">
                    <div class="h-12 w-12 rounded-xl bg-brand-600/10 border border-brand-500/15 flex items-center justify-center mb-4">
                        <i data-lucide="message-square" class="h-6 w-6 text-brand-400"></i>
                    </div>
                    <h4 class="text-sm font-semibold text-white">Start the conversation</h4>
                    <p class="text-gray-400 text-xs mt-1 leading-relaxed mb-5">
                        Ask anything about "${filename}". The retrieval engine will fetch relevant chunks, rerank them, and generate grounded AI responses.
                    </p>

                    <div class="flex flex-wrap items-center justify-center gap-2 mt-2">
                        <button onclick="userInput.value='Summarize this document'; userInput.focus();"
                            class="px-3 py-1.5 rounded-lg bg-darkPanel border border-darkBorder text-[10px] hover:border-brand-500/30 transition">
                            Summarize Document
                        </button>

                        <button onclick="userInput.value='Extract methodologies'; userInput.focus();"
                            class="px-3 py-1.5 rounded-lg bg-darkPanel border border-darkBorder text-[10px] hover:border-brand-500/30 transition">
                            Extract Methodologies
                        </button>

                        <button onclick="userInput.value='Explain key findings'; userInput.focus();"
                            class="px-3 py-1.5 rounded-lg bg-darkPanel border border-darkBorder text-[10px] hover:border-brand-500/30 transition">
                            Explain Findings
                        </button>
                    </div>
                </div>
            `;
            lucide.createIcons();
        }

        // Send Chat Prompt & Stream Response (SSE)
        chatForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            if (!activeFileId || isGenerating) return;

            const query = userInput.value.trim();
            const activeGenId = window.activeCollectionId || activeFileId;
            window.activeGenerations[activeGenId] = true;
            const submittedGenId = activeGenId;
            if (!query) return;

            // Disable input while generating
            userInput.value = "";
            userInput.style.height = "38px";
            isGenerating = true;
            toggleInputState(true);

            // Remove empty states if present
            const slate = chatFeed.querySelector("#blank-slate") || chatFeed.querySelector("#empty-state-isolated");
            if (slate) slate.remove();

            // 1. Append User Message
            appendMessageBubble("user", query, null, false);
            scrollToBottom();

            // 2. Setup streaming Assistant bubble
            const messageId = "msg-" + Date.now();
            const assistantBubble = appendMessageBubble("assistant", "", null, true, messageId);
            const contentDiv = assistantBubble.querySelector(".message-content");

            contentDiv.innerHTML = `
                <div class="flex flex-col gap-2 text-sm text-gray-400">
                    <div class="flex items-center gap-2">
                        <span class="h-2 w-2 rounded-full bg-brand-400 animate-pulse"></span>
                        Retrieving relevant document chunks...
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="h-2 w-2 rounded-full bg-indigo-400 animate-pulse"></span>
                        Running hybrid reranking pipeline...
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="h-2 w-2 rounded-full bg-emerald-400 animate-pulse"></span>
                        Generating grounded response...
                    </div>
                </div>
            `;
            scrollToBottom();

            try {
                const provider = document.getElementById("llm-provider").value;
                const topK = parseInt(document.getElementById("rag-top-k").value) || 5;

                console.log("Provider:", provider);
                console.log("Top K:", topK);

                currentChatController = new AbortController();
                const response = await fetch(`${API_BASE}/files/${activeFileId}/chat`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    signal: currentChatController.signal,
                    body: JSON.stringify({
                        query: query,
                        provider: provider,
                        top_k: topK
                    })
                });


                if (!response.ok) {
                    const errObj = await response.json();
                    throw new Error(errObj.detail || "Server failed to stream");
                }

                // Create Reader to handle SSE chunked stream
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let accumulatedAnswer = "";
                let buffer = "";

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split("\n");
                    buffer = lines.pop(); // keep partial trailing line

                    for (const line of lines) {
                        const trimmed = line.trim();
                        if (!trimmed) continue;

                        if (trimmed.startsWith("data: ")) {
                            // Try to parse token or source
                            const dataPayload = trimmed.replace("data: ", "").trim();
                            if (dataPayload === "[DONE]") {
                                break;
                            }

                            try {
                                const parsedVal = JSON.parse(dataPayload);
                                if (Array.isArray(parsedVal)) {
                                    // Save the sources in global citations map
                                    window.messageCitations = window.messageCitations || {};
        window.activeGenerations = window.activeGenerations || {};
                                    window.messageCitations[messageId] = parsedVal;

                                    // Render Citations badge under bubble
                                    const badgeContainer = assistantBubble.querySelector(".citations-badge-container");
                                    if (badgeContainer) {
                                        badgeContainer.innerHTML = `
                                            <button onclick="openCitationsSidebar('${messageId}')" class="px-2.5 py-1 rounded-lg bg-brand-500/10 text-brand-400 border border-brand-500/15 hover:bg-brand-500/20 hover:border-brand-500/30 text-[10px] font-semibold flex items-center gap-1.5 transition select-none">
                                                <i data-lucide="database" class="h-3 w-3"></i>
                                                <span>${parsedVal.length} Grounded Citations ↗</span>
                                            </button>
                                        `;
                                        badgeContainer.classList.remove("hidden");
                                        lucide.createIcons();
                                    }

                                    // Automatically open the citations sidebar immediately
                                    openCitationsSidebar(messageId);

                                } else if (typeof parsedVal === "string") {
                                    // Token emission
                                    accumulatedAnswer += parsedVal;
                                    const renderedContent = linkifyCitations(marked.parse(accumulatedAnswer), messageId);
                                    contentDiv.innerHTML = renderedContent;
                                    Prism.highlightAllUnder(contentDiv);

                                    // Enable copy code buttons
                                    setupCopyButtons(contentDiv);

                                    scrollToBottom();
                                }
                            } catch (err) {
                                // Fallback for raw text token
                                accumulatedAnswer += dataPayload;
                                const renderedContent = linkifyCitations(marked.parse(accumulatedAnswer), messageId);
                                contentDiv.innerHTML = renderedContent;
                                scrollToBottom();
                            }
                        }
                    }
                }

                // Finish streaming
                contentDiv.classList.remove("typing-cursor");

            } catch (err) {
                contentDiv.classList.remove("typing-cursor");
                if (err.name === 'AbortError') {
                    contentDiv.innerHTML += `<div class="mt-4 text-xs font-semibold text-gray-500 flex items-center gap-1.5"><i data-lucide="square" class="h-3 w-3 fill-current"></i> Generation stopped by user.</div>`;
                } else {
                    console.error(err);
                    contentDiv.innerHTML = `<p class="text-rose-400 font-semibold flex items-center gap-1.5"><i data-lucide="alert-circle" class="h-4 w-4"></i> Error streaming response: ${err.message}</p>`;
                }
                lucide.createIcons();
            } finally {
                delete window.activeGenerations[submittedGenId];
                const currentActiveId = window.activeCollectionId || activeFileId;
                if (currentActiveId === submittedGenId) {
                    isGenerating = false;
                    currentChatController = null;
                    toggleInputState(false);
                    if (window.activeCollectionId) {
                        if (typeof selectCollection === 'function') selectCollection(window.activeCollectionId);
                    } else if (activeFileId) {
                        selectWorkspace(activeFileId, 'ready');
                    }
                } else if (currentActiveId) {
                    // Background generation finished but user is looking at another chat
                    showToast('Background Task Finished', 'A background response has finished generating.', 'success');
                }
            }
        });

        // Toggle form inputs
        function toggleInputState(disabled, isIndexing = false) {
            userInput.disabled = disabled;
            if (disabled) {
                userInput.placeholder = isIndexing ? "Document is indexing... Chat will enable shortly." : "Generating response...";
                chatForm.classList.add("opacity-50", "cursor-not-allowed");
                btnSend.classList.add("hidden");
                if (!isIndexing) btnStop.classList.remove("hidden");
            } else {
                userInput.placeholder = "Ask a question about this document...";
                chatForm.classList.remove("opacity-50", "cursor-not-allowed");
                btnSend.classList.remove("hidden");
                btnStop.classList.add("hidden");
                userInput.focus();
            }
        }

        // Global map storing message citations
        window.messageCitations = window.messageCitations || {};
        window.activeGenerations = window.activeGenerations || {};

        // Open Citations Sidebar for a specific message and render its RAG sources
        function openCitationsSidebar(messageId) {
            const sources = window.messageCitations[messageId];
            if (!sources || sources.length === 0) return;

            citationsSidebar.classList.remove("hidden");
            citationsSidebar.classList.remove("collapsed");
            citationsSidebar.style.width = `${lastRightWidth}px`;

            const rightResizer = document.getElementById("right-resizer");
            if (rightResizer) {
                rightResizer.classList.remove("hidden");
                rightResizer.style.right = `${lastRightWidth}px`;
            }
            rightCollapsed = false;
            if (window.updateResizerChevrons) {
                window.updateResizerChevrons();
            }

            citationsSidebarContent.innerHTML = `
                <div class="flex flex-col gap-3">
                    <div class="px-1 text-[9px] font-bold text-gray-500 uppercase tracking-widest mb-1">
                        Sources for message
                    </div>
                    ${sources.map(src => {
                        const semanticScorePct = (src.score * 100).toFixed(0);
                        const rerankScore = src.rerank_score.toFixed(3);
                        const prefix = src.is_table ? "TABLE" : "TEXT";
                        const bgBadgeColor = src.is_table ? "bg-cyan-500/10 text-cyan-400 border-cyan-500/20" : "bg-brand-500/10 text-brand-400 border-brand-500/20";

                        return `
                            <div id="sidebar-source-${messageId}-${src.source_index}"
                                onclick="showSourceModal(${src.source_index})"
                                class="p-4 bg-darkPanel/40 border border-darkBorder/40 hover:bg-darkPanel/60 hover:border-brand-500/30 rounded-xl cursor-pointer transition-all duration-300 shadow-md">
                                
                                <div class="flex items-start justify-between mb-2">
                                    <div class="flex flex-col gap-1.5 min-w-0">
                                        <div class="flex items-center gap-2">
                                            <span class="text-[9px] font-bold px-2 py-0.5 rounded border ${bgBadgeColor} shrink-0">[Source ${src.source_index}] ${prefix}</span>
                                            ${src.filename ? `<span class="text-[10px] text-brand-300 font-semibold truncate max-w-[120px]" title="${src.filename}"><i data-lucide="file-text" class="h-2.5 w-2.5 inline mb-0.5 mr-0.5"></i>${src.filename}</span>` : ''}
                                        </div>
                                        ${src.header ? `<span class="text-[9px] text-gray-400 font-medium truncate max-w-[180px]" title="${src.header}">${src.header}</span>` : ''}
                                    </div>
                                    <div class="h-6 w-6 rounded bg-darkBorder flex items-center justify-center text-gray-400 hover:text-white transition shrink-0 ml-2">
                                        <i data-lucide="maximize-2" class="h-3 w-3"></i>
                                    </div>
                                </div>
                                
                                <p class="font-sans text-[11px] leading-relaxed text-gray-300">
                                    ${escapeHtml(src.content.substring(0, 200))}${src.content.length > 200 ? '...' : ''}
                                </p>
                                
                                <div class="flex items-center justify-between mt-3 pt-2 border-t border-darkBorder/20 text-[9px] font-mono text-gray-500">
                                    <span>Dense Match: ${semanticScorePct}%</span>
                                    <span>Rerank Score: ${rerankScore}</span>
                                </div>
                            </div>
                        `;
                    }).join("")}
                </div>
            `;

            currentSources = sources;
            lucide.createIcons();
        }

        // Keep renderSourcesSidebar as a compatible wrapper for backwards compatibility
        function renderSourcesSidebar(sources) {
            const dummyMsgId = "current-streaming-msg";
            window.messageCitations = window.messageCitations || {};
        window.activeGenerations = window.activeGenerations || {};
            window.messageCitations[dummyMsgId] = sources;
            openCitationsSidebar(dummyMsgId);
        }

        function toggleSourcesCollapse(button) {
            const list = button.nextElementSibling;
            const arrow = button.querySelector("[data-lucide='chevron-down']");

            if (list.classList.contains("hidden")) {
                list.classList.remove("hidden");
                list.classList.add("flex");
                arrow.style.transform = "rotate(180deg)";
            } else {
                list.classList.add("hidden");
                list.classList.remove("flex");
                arrow.style.transform = "rotate(0deg)";
            }
        }

        // Linkify citation markers like [Source 1] to interactive links
        function linkifyCitations(htmlContent, messageId) {
            if (!messageId) return htmlContent;
            return htmlContent.replace(/\[Source (\d+)\]/g, (match, p1) => {
                return `<a href="#" onclick="event.preventDefault(); highlightSource('${messageId}', ${p1})" class="px-1.5 py-0.5 rounded bg-brand-500/10 hover:bg-brand-500/20 border border-brand-500/20 text-brand-400 font-semibold text-[11px] transition inline-flex items-center gap-0.5" title="Click to view Source ${p1} context">${match}</a>`;
            });
        }

        // Highlight a source in the sidebar with a gorgeous pulse animation
        function highlightSource(messageId, sourceIndex) {
            openCitationsSidebar(messageId);
            
            const sourceCard = document.getElementById(`sidebar-source-${messageId}-${sourceIndex}`);
            if (sourceCard) {
                sourceCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                
                // Add high-visibility highlight styles
                sourceCard.classList.remove("border-darkBorder/40", "bg-darkPanel/40");
                sourceCard.classList.add("border-brand-500/80", "bg-brand-500/10", "ring-1", "ring-brand-500/50", "scale-[1.02]");
                
                setTimeout(() => {
                    sourceCard.classList.remove("border-brand-500/80", "bg-brand-500/10", "ring-1", "ring-brand-500/50", "scale-[1.02]");
                    sourceCard.classList.add("border-darkBorder/40", "bg-darkPanel/40");
                }, 2000);
            }
        }

        // Append message bubble to chat feed
        function appendMessageBubble(role, content, sources = null, isLive = false, msgId = null) {
            const messageId = msgId || ("msg-" + Date.now() + "-" + Math.random().toString(36).substr(2, 9));
            const bubble = document.createElement("div");
            bubble.className = `flex gap-4 ${role === "user" ? "justify-end" : "justify-start"} fade-in`;
            bubble.dataset.messageId = messageId;

            const isUser = role === "user";
            const cardBg = isUser ? "bg-brand-600 text-white rounded-tr-none" : "glass-card text-gray-200 rounded-tl-none";
            const avatarHtml = isUser ? `
                <div class="h-9 w-9 rounded-xl bg-brand-800 text-brand-300 flex items-center justify-center shrink-0 border border-brand-600/30">
                    <i data-lucide="user" class="h-4.5 w-4.5"></i>
                </div>
            ` : `
                <div class="h-9 w-9 rounded-xl bg-indigo-500/10 text-indigo-400 flex items-center justify-center shrink-0 border border-indigo-500/15">
                    <i data-lucide="bot" class="h-4.5 w-4.5"></i>
                </div>
            `;

            // Register historical sources in global map
            if (sources && sources.length > 0) {
                window.messageCitations = window.messageCitations || {};
        window.activeGenerations = window.activeGenerations || {};
                window.messageCitations[messageId] = sources;
            }

            const parsedHtml = isUser ? escapeHtml(content) : linkifyCitations(marked.parse(content), messageId);
            const liveCursorClass = isLive ? "typing-cursor" : "";

            let badgeHtml = "";
            if (!isUser) {
                if (sources && sources.length > 0) {
                    badgeHtml = `
                        <div class="citations-badge-container mt-2">
                            <button onclick="openCitationsSidebar('${messageId}')" class="px-2.5 py-1 rounded-lg bg-brand-500/10 text-brand-400 border border-brand-500/15 hover:bg-brand-500/20 hover:border-brand-500/30 text-[10px] font-semibold flex items-center gap-1.5 transition select-none">
                                <i data-lucide="database" class="h-3 w-3"></i>
                                <span>${sources.length} Grounded Citations ↗</span>
                            </button>
                        </div>
                    `;
                } else {
                    badgeHtml = `<div class="citations-badge-container mt-2 ${isLive ? '' : 'hidden'}"></div>`;
                }
            }

            bubble.innerHTML = `
                <div class="flex gap-3 max-w-3xl ${isUser ? 'flex-row-reverse' : 'flex-row'}">
                    ${avatarHtml}
                    <div class="flex flex-col group relative max-w-full">
                        <div class="px-4.5 py-3 rounded-2xl text-sm leading-relaxed border border-white/[0.02] shadow-md ${cardBg} overflow-x-auto">
                            <div class="message-content prose max-w-none text-gray-200 ${liveCursorClass}">
                                ${parsedHtml}
                            </div>
                            ${badgeHtml}
                        </div>
                        <div class="flex items-center gap-2 mt-1 ${isUser ? 'justify-end' : 'justify-start'} px-1">
                            <span class="text-[9px] text-gray-500">
                                ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </span>
                            <button class="text-gray-500 hover:text-gray-300 transition-colors opacity-0 group-hover:opacity-100" title="Copy Message" onclick="copyMessageText(this)">
                                <i data-lucide="copy" class="h-3 w-3"></i>
                            </button>
                        </div>
                    </div>
                </div>
            `;

            chatFeed.appendChild(bubble);
            lucide.createIcons();

            if (!isUser) {
                Prism.highlightAllUnder(bubble.querySelector(".message-content"));
                setupCopyButtons(bubble.querySelector(".message-content"));
            }

            return bubble;
        }

        // Setup "Copy" button inside code blocks
        function setupCopyButtons(container) {
            container.querySelectorAll("pre").forEach(pre => {
                // Ensure no duplicates
                if (pre.querySelector(".btn-copy-code")) return;

                pre.style.position = "relative";
                const btn = document.createElement("button");
                btn.className = "btn-copy-code absolute top-3 right-3 p-1.5 rounded bg-darkPanel/80 hover:bg-darkBorder border border-darkBorder text-gray-400 hover:text-white transition-all scale-90 opacity-0 group-hover:opacity-100 duration-200";
                btn.title = "Copy Code";
                btn.innerHTML = `<i data-lucide="copy" class="h-3.5 w-3.5"></i>`;

                // Add hover groups
                pre.classList.add("group");
                pre.appendChild(btn);

                btn.addEventListener("click", () => {
                    const code = pre.querySelector("code").innerText;
                    navigator.clipboard.writeText(code).then(() => {
                        btn.innerHTML = `<i data-lucide="check" class="h-3.5 w-3.5 text-emerald-400"></i>`;
                        lucide.createIcons();
                        showToast("Copied", "Code snippet copied to clipboard.", "success");
                        setTimeout(() => {
                            btn.innerHTML = `<i data-lucide="copy" class="h-3.5 w-3.5"></i>`;
                            lucide.createIcons();
                        }, 2000);
                    });
                });
            });
            lucide.createIcons();
        }

        // Copy entire message text
        function copyMessageText(btn) {
            const wrapper = btn.closest('.group');
            if (!wrapper) return;
            const contentDiv = wrapper.querySelector('.message-content');
            if (!contentDiv) return;
            
            const textToCopy = contentDiv.innerText;
            
            navigator.clipboard.writeText(textToCopy).then(() => {
                const originalHtml = btn.innerHTML;
                btn.innerHTML = `<i data-lucide="check" class="h-3 w-3 text-emerald-400"></i>`;
                lucide.createIcons();
                setTimeout(() => {
                    btn.innerHTML = originalHtml;
                    lucide.createIcons();
                }, 2000);
            }).catch(err => {
                console.error("Failed to copy text: ", err);
            });
        }
        btnExportChat.addEventListener("click", exportChat);

        function exportChat() {

            const messages = document.querySelectorAll(
                ".message-content"
            );

            let content = "# ContextIQ Chat Export\n\n";

            const file = files.find(
                f => f.id === activeFileId
            );

            content += `Document: ${file?.filename || "Unknown"}\n\n`;
            content += `Generated: ${new Date().toLocaleString()}\n\n`;
            content += "---------------------------------\n\n";

            messages.forEach(msg => {
                content += msg.innerText + "\n\n";
            });

            const blob = new Blob(
                [content],
                { type: "text/plain" }
            );

            const url = URL.createObjectURL(blob);

            const a = document.createElement("a");

            a.href = url;
            a.download = `contextiq-chat-${Date.now()}.txt`;

            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);

            URL.revokeObjectURL(url);

            showToast(
                "Export Complete",
                "Chat downloaded successfully.",
                "success"
            );
        }
        // Clear Chat History Handler
        btnClearChat.addEventListener("click", async () => {
            if (!activeFileId || isGenerating) return;
            if (!confirm("Are you sure you want to wipe the conversational history for this workspace?")) return;

            try {
                const response = await fetch(`${API_BASE}/files/${activeFileId}/clear`, { method: "POST" });
                if (response.ok) {
                    citationsSidebar.classList.add("hidden");
                    const rr2 = document.getElementById("right-resizer");
                    if (rr2) rr2.classList.add("hidden");
                    showToast("History Cleared", "Message logs cleared for this workspace.", "success");
                    selectWorkspace(activeFileId, "ready");
                }
            } catch (err) {
                console.error(err);
            }
        });

        // Delete File Handler
        async function quickDeleteFile(fileId) {
            const file = files.find(f => f.id === fileId);

            if (!file) return;

            if (!confirm(`Delete "${file.filename}"?`)) return;

            try {
                const response = await fetch(`${API_BASE}/files/${fileId}`, {
                    method: "DELETE"
                });

                if (!response.ok) {
                    throw new Error("Delete failed");
                }

                // Reset active workspace if current file deleted
                if (activeFileId === fileId) {
                    activeFileId = null;

                    citationsSidebar.classList.add("hidden");
                    const rr3 = document.getElementById("right-resizer");
                    if (rr3) rr3.classList.add("hidden");

                    chatHeader.classList.add("hidden");
                    chatInputBar.classList.add("hidden");

                    chatFeed.innerHTML = "";

                    blankSlate.classList.remove("hidden");
                }

                // Remove from local array instantly
                files = files.filter(f => f.id !== fileId);

                // Re-render sidebar
                renderFilesList();

                showToast(
                    "Document Deleted",
                    `"${file.filename}" removed successfully.`,
                    "success"
                );

            } catch (err) {
                console.error(err);

                showToast(
                    "Delete Failed",
                    "Could not delete document.",
                    "error"
                );
            }
        }
        btnDeleteFile.addEventListener("click", async () => {
            if (!activeFileId || isGenerating) return;
            const file = files.find(f => f.id === activeFileId);
            if (!file) return;

            // Custom Confirm Modal to bypass browser dialog blocking
            const confirmModal = document.createElement("div");
            confirmModal.className = "fixed inset-0 z-[200] flex items-center justify-center bg-[#0f111a]/80 backdrop-blur-sm fade-in";
            confirmModal.innerHTML = `
                <div class="bg-darkPanel border border-darkBorder rounded-2xl p-6 shadow-2xl max-w-sm w-full mx-4 transform transition-all scale-100">
                    <div class="flex items-center gap-3 text-rose-400 mb-2">
                        <div class="h-10 w-10 rounded-full bg-rose-500/10 flex items-center justify-center shrink-0">
                            <i data-lucide="alert-triangle" class="h-5 w-5"></i>
                        </div>
                        <h3 class="font-bold text-lg text-white">Delete Document?</h3>
                    </div>
                    <p class="text-sm text-gray-400 mb-6 mt-4">Are you sure you want to permanently delete "<span class="text-white font-medium">${file.filename}</span>"?<br><br>This will clear its conversational logs and dense database embeddings.</p>
                    <div class="flex gap-3 justify-end">
                        <button id="btn-cancel-del" class="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white bg-darkCard hover:bg-white/5 rounded-lg border border-darkBorder transition">Cancel</button>
                        <button id="btn-confirm-del" class="px-4 py-2 text-sm font-medium text-white bg-rose-500 hover:bg-rose-600 rounded-lg shadow-lg shadow-rose-500/20 transition">Delete Permanently</button>
                    </div>
                </div>
            `;
            document.body.appendChild(confirmModal);
            lucide.createIcons();

            confirmModal.querySelector("#btn-cancel-del").addEventListener("click", () => confirmModal.remove());
            
            confirmModal.querySelector("#btn-confirm-del").addEventListener("click", async () => {
                confirmModal.remove();
                try {
                    const response = await fetch(`${API_BASE}/files/${activeFileId}`, { method: "DELETE" });
                    if (response.ok) {
                        showToast("Document Deleted", `"${file.filename}" deleted from isolated storage.`, "success");

                        // Reset Workspace
                        activeFileId = null;
                        chatHeader.classList.add("hidden");
                        chatInputBar.classList.add("hidden");
                        chatFeed.innerHTML = "";
                        blankSlate.classList.remove("hidden");

                        // Remove from local array instantly
                        files = files.filter(f => f.id !== file.id);
                        renderFilesList();
                    } else {
                        showToast("Delete Failed", "Could not delete document from server.", "error");
                    }
                } catch (err) {
                    console.error(err);
                    showToast("Delete Failed", "Network error while deleting document.", "error");
                }
            });
        });

        // Drag and Drop File Handlers
        function initDragAndDrop() {
            ["dragenter", "dragover"].forEach(eventName => {
                dropZone.addEventListener(eventName, (e) => {
                    e.preventDefault();
                    dropZone.classList.add("border-brand-500/50", "bg-brand-500/[0.04]");
                }, false);
            });

            ["dragleave", "drop"].forEach(eventName => {
                dropZone.addEventListener(eventName, (e) => {
                    e.preventDefault();
                    dropZone.classList.remove("border-brand-500/50", "bg-brand-500/[0.04]");
                }, false);
            });

            dropZone.addEventListener("drop", (e) => {
                const dt = e.dataTransfer;
                const filesList = dt.files;
                if (filesList.length > 0) {
                    const newTab = createDocViewTab();
                    handleFileUpload(filesList[0], newTab);
                }
            });

            // Global drop for normal Documents (when not in a collection)
            document.body.addEventListener("dragover", (e) => {
                // If we are NOT in a collection, allow drop
                if (typeof activeCollectionId === 'undefined' || !activeCollectionId) {
                    e.preventDefault();
                }
            }, false);

            document.body.addEventListener("drop", (e) => {
                // If we are NOT in a collection
                if (typeof activeCollectionId === 'undefined' || !activeCollectionId) {
                    // Prevent handling if dropped exactly on the small dropZone (it's handled above)
                    if (!dropZone.contains(e.target)) {
                        e.preventDefault();
                        const dt = e.dataTransfer;
                        if (dt && dt.files && dt.files.length > 0) {
                            const docModal = createDocViewModal(dt.files[0].name);
                            handleFileUpload(dt.files[0], docModal);
                        }
                    }
                }
            }, false);

            dropZone.addEventListener("click", () => fileInput.click());
            fileInput.addEventListener("change", (e) => {
                if (e.target.files.length > 0) {
                    if (e.target.files.length > 1) {
                        // Multi-file select: don't open modal, just upload all
                        showToast("Uploading", `Uploading ${e.target.files.length} documents...`, "success");
                        Array.from(e.target.files).forEach(f => handleFileUpload(f, null));
                    } else {
                        // Single file select: auto-open modal
                        const docModal = createDocViewModal(e.target.files[0].name);
                        handleFileUpload(e.target.files[0], docModal);
                    }
                }
                e.target.value = ""; // Reset input so same file(s) can be selected again
            });
        }

        // Helper to open document view in a fullscreen modal synchronously
        function createDocViewModal(filename = "") {
            if (!autoOpenOnUpload) return null;
            
            // Browsers cannot render DOCX, XLSX, or CSV natively.
            const ext = filename.split('.').pop().toLowerCase();
            const viewableExts = ['pdf', 'txt', 'md', 'markdown', 'png', 'jpg', 'jpeg'];
            if (ext && !viewableExts.includes(ext)) {
                return null; // Skip modal for unviewable files
            }
            
            const modal = document.createElement("div");
            modal.className = "fixed inset-0 z-[100] flex flex-col bg-[#0f111a]/95 backdrop-blur-md transition-all duration-300";
            
            // Initial loading state
            modal.innerHTML = `
                <div class="flex-1 flex flex-col items-center justify-center fade-in" id="modal-loading-state">
                    <div class="h-12 w-12 rounded-xl bg-brand-600/10 border border-brand-500/15 flex items-center justify-center mb-4 animate-pulse">
                        <i data-lucide="loader-2" class="h-6 w-6 text-brand-400 animate-spin"></i>
                    </div>
                    <div class="text-white font-semibold text-sm">Opening Document...</div>
                    <p class="text-gray-400 text-xs mt-1">Please wait while the document is uploaded and prepared</p>
                </div>
                <div id="modal-iframe-container" class="flex-1 hidden w-full h-full relative p-4 pb-0">
                    <!-- Close button -->
                    <button onclick="this.closest('.fixed').remove()" class="absolute top-6 right-8 h-10 w-10 bg-darkPanel/90 backdrop-blur-xl border border-darkBorder rounded-full flex items-center justify-center text-gray-300 hover:text-white hover:border-brand-500/50 hover:bg-brand-500/20 transition z-50 shadow-2xl" title="Close Viewer">
                        <i data-lucide="x" class="h-5 w-5"></i>
                    </button>
                </div>
            `;
            
            document.body.appendChild(modal);
            lucide.createIcons();
            return modal;
        }

        // Upload to FastAPI endpoint
        async function handleFileUpload(file, docModal = null) {
            // Prevent duplicate uploads on the frontend
            const existingFile = files.find(f => f.filename === file.name);
            if (existingFile) {
                showToast("Duplicate File", `"${file.name}" is already uploaded.`, "error");
                return;
            }

            const formData = new FormData();
            formData.append("file", file);

            showToast("Uploading File", `"${file.name}" is uploading to parsing pipeline.`, "info");

            try {
                // Instantly append dummy file with status loading
                const dummyId = "dummy-" + Date.now();
                files.unshift({
                    id: dummyId,
                    filename: file.name,
                    file_size: file.size,
                    file_type: file.name.split(".").pop(),
                    status: "processing",
                    uploaded_at: new Date().toISOString()
                });
                renderFilesList();

                // Route to active collection if one is currently selected
                if (typeof window.activeCollectionId !== 'undefined' && window.activeCollectionId) {
                    formData.append("collection_id", window.activeCollectionId);
                }

                const response = await fetch(`${API_BASE}/files/upload`, {
                    method: "POST",
                    body: formData
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || "Server indexing failed");
                }

                const data = await response.json();
                showToast("File Uploaded", `"${file.name}" uploaded successfully. Indexing RAG pipeline in background...<br><a href="${API_BASE}/files/${data.file.id}/view" target="_blank" class="text-brand-400 hover:underline font-semibold block mt-1.5 flex items-center gap-1"><i data-lucide="external-link" class="h-3 w-3 inline"></i> Open Original File</a>`, "success");

                // Navigate the modal to the actual document URL
                if (docModal) {
                    const loadingState = docModal.querySelector("#modal-loading-state");
                    const iframeContainer = docModal.querySelector("#modal-iframe-container");
                    
                    if (loadingState && iframeContainer) {
                        loadingState.classList.add("hidden");
                        iframeContainer.classList.remove("hidden");
                        
                        const iframe = document.createElement("iframe");
                        iframe.src = `${API_BASE}/files/${data.file.id}/view`;
                        iframe.className = "w-full h-full border-0 rounded-t-xl bg-white shadow-2xl";
                        iframeContainer.insertBefore(iframe, iframeContainer.firstChild);
                    }
                }

                // Swap dummy with actual file
                const idx = files.findIndex(f => f.id === dummyId);
                if (idx !== -1) {
                    files[idx] = data.file;
                }
                renderFilesList();
                
                // Automatically switch to the newly uploaded document's workspace
                selectWorkspace(data.file.id, "processing");

            } catch (err) {
                console.error(err);
                if (newTab) {
                    newTab.close();
                }
                showToast("Upload Error", `Could not index document: ${err.message}`, "error");
                fetchFiles(); // Re-sync
            }
        }

        // Input textarea utility
        function initTextareaAutoGrow() {
            userInput.addEventListener("input", function () {
                this.style.height = "auto";
                this.style.height = (this.scrollHeight - 4) + "px";
                if (this.value.trim() === "") {
                    this.style.height = "38px";
                }
            });

            userInput.addEventListener("keydown", function (e) {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    chatForm.dispatchEvent(new Event("submit"));
                }
            });
        }

        // Helper utilities
        function scrollToBottom() {
            chatFeed.scrollTop = chatFeed.scrollHeight;
        }
        function showSourceModal(index) {
            const src = currentSources.find(
                s => s.source_index === index
            );

            if (!src) return;

            document.getElementById("source-modal-content").innerText =
                src.content;

            document.getElementById("source-modal")
                .classList.remove("hidden");

            document.getElementById("source-modal")
                .classList.add("flex");
        }

        function closeSourceModal() {
            document.getElementById("source-modal")
                .classList.add("hidden");

            document.getElementById("source-modal")
                .classList.remove("flex");
        }
        function escapeHtml(str) {
            return str
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }
        
        window.addFileToContext = async function() {
            const activeType = localStorage.getItem('contextiq_active_type');
            if (activeType === 'collection') {
                if (typeof window.openCollectionFilesModal === 'function') {
                    window.openCollectionFilesModal();
                }
                return;
            }
            
            if (activeType === 'file' && activeFileId) {
                const file = files.find(f => f.id === activeFileId);
                if (!file) return;
                
                showToast("Creating Collection", "Creating a new collection from this document...", "info");
                
                try {
                    // Create collection
                    const colName = `Collection with ${file.filename.slice(0, 20)}...`;
                    const res = await fetch(`${API_BASE}/collections`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ name: colName })
                    });
                    if (!res.ok) {
                        showToast("Error", "Failed to create collection", "error");
                        return;
                    }
                    const col = await res.json();
                    
                    // Add current file to collection
                    await fetch(`${API_BASE}/collections/${col.id}/files`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ file_id: file.id })
                    });
                    
                    // Switch to collection
                    if (typeof fetchCollections === 'function') {
                        await fetchCollections();
                        const tab = document.getElementById('tab-collections');
                        if (tab) tab.click();
                        if (typeof selectCollection === 'function') {
                            selectCollection(col.id);
                        }
                    }
                    
                    // Open modal
                    setTimeout(() => {
                        if (typeof window.openCollectionFilesModal === 'function') {
                            window.openCollectionFilesModal(col.id);
                        }
                    }, 500);
                    
                } catch (e) {
                    console.error(e);
                    showToast("Error", "Failed to create collection", "error");
                }
            }
        };
    