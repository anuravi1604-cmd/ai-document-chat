
// --- COLLECTIONS UI LOGIC ---
const tabDocs = document.getElementById("tab-docs");
const tabCollections = document.getElementById("tab-collections");
const docsContainer = document.getElementById("docs-container");
const collectionsContainer = document.getElementById("collections-container");
const collectionsList = document.getElementById("collections-list");

if (tabDocs && tabCollections) {
    let collections = [];
    window.activeCollectionId = null;

    tabDocs.addEventListener("click", () => {
        tabDocs.classList.add("text-white", "border-brand-500");
        tabDocs.classList.remove("text-gray-500", "border-transparent");
        tabCollections.classList.remove("text-white", "border-brand-500");
        tabCollections.classList.add("text-gray-500", "border-transparent");
        docsContainer.classList.remove("hidden");
        collectionsContainer.classList.add("hidden");
        window.activeCollectionId = null;
    });

    tabCollections.addEventListener("click", () => {
        tabCollections.classList.add("text-white", "border-brand-500");
        tabCollections.classList.remove("text-gray-500", "border-transparent");
        tabDocs.classList.remove("text-white", "border-brand-500");
        tabDocs.classList.add("text-gray-500", "border-transparent");
        collectionsContainer.classList.remove("hidden");
        docsContainer.classList.add("hidden");
        
        // Use existing variables safely
        if(typeof activeFileId !== 'undefined') activeFileId = null;
        if(typeof renderChatState === 'function') renderChatState();
        fetchCollections();
    });

    tabDocs.addEventListener("dragover", (e) => {
        e.preventDefault();
        if(tabDocs.classList.contains("text-gray-500")) tabDocs.click();
    });

    tabCollections.addEventListener("dragover", (e) => {
        e.preventDefault();
        if(tabCollections.classList.contains("text-gray-500")) tabCollections.click();
    });

    async function fetchCollections() {
        try {
            const response = await fetch(`${API_BASE}/collections`);
            if (response.ok) {
                collections = await response.json();
                renderCollectionsList();
            }
        } catch (err) {
            console.error(err);
        }
    }

    async function createNewCollection() {
        const name = prompt("Enter a name for the new collection:", "New Collection");
        if (!name) return;
        try {
            const res = await fetch(`${API_BASE}/collections`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name })
            });
            if (res.ok) {
                const newCol = await res.json();
                await fetchCollections();
                selectCollection(newCol.id, newCol.name);
                showToast("Success", "Collection created", "success");
            } else {
                const err = await res.json();
                showToast("Error", err.detail || "Failed to create collection", "error");
            }
        } catch (e) {
            console.error(e);
            showToast("Error", "An unexpected error occurred", "error");
        }
    }
    window.createNewCollection = createNewCollection;

    async function deleteCollection(id) {
        if(!confirm("Delete this collection?")) return;
        try {
            await fetch(`${API_BASE}/collections/${id}`, { method: 'DELETE' });
            if(window.activeCollectionId === id) {
                window.location.reload();
                return;
            }
            fetchCollections();
        } catch (e) { console.error(e); }
    }
    window.deleteCollection = deleteCollection;

    // Edit Collection now opens the unified modal
    async function editCollection(id) {
        window.openCollectionFilesModal(id);
    }
    window.editCollection = editCollection;

    let draggedFileId = null;
    window.setDraggedFileId = function(id) { draggedFileId = id; }

    function renderCollectionsList() {
        if (collections.length === 0) {
            collectionsList.innerHTML = `<div class="text-center py-8 text-gray-500"><i data-lucide="folders" class="h-8 w-8 mx-auto mb-2 text-gray-600"></i><p class="text-xs">No collections created</p></div>`;
            lucide.createIcons();
            return;
        }

        collectionsList.innerHTML = collections.map(col => {
            const isActive = col.id === window.activeCollectionId;
            let itemClass = isActive ? "bg-gradient-to-tr from-brand-600/10 to-indigo-500/[0.03] border border-brand-500/25 shadow-lg shadow-brand-500/[0.02]" : "bg-darkPanel/40 hover:bg-darkPanel border border-darkBorder/40";
            
            return `
                <div 
                    onclick="selectCollection('${col.id}')"
                    ondragover="event.preventDefault(); this.classList.add('border-brand-500');"
                    ondragleave="this.classList.remove('border-brand-500');"
                    ondrop="event.preventDefault(); this.classList.remove('border-brand-500'); addDraggedFileToCollection('${col.id}')"
                    class="relative p-3.5 rounded-xl cursor-pointer transition flex flex-col group ${itemClass}">
                    <div class="absolute top-2.5 right-2.5 flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition z-20">
                        <button onclick="event.stopPropagation(); window.openCollectionFilesModal('${col.id}')" title="Add File" class="h-6 w-6 rounded bg-darkPanel border border-darkBorder/60 flex items-center justify-center text-gray-400 hover:text-brand-400 hover:border-brand-500/30 transition">
                            <i data-lucide="plus" class="h-3.5 w-3.5"></i>
                        </button>
                        <button onclick="event.stopPropagation(); editCollection('${col.id}')" title="Edit Collection" class="h-6 w-6 rounded bg-darkPanel border border-darkBorder/60 flex items-center justify-center text-gray-400 hover:text-blue-400 hover:border-blue-500/30 transition">
                            <i data-lucide="pencil" class="h-3 w-3"></i>
                        </button>
                        <button onclick="event.stopPropagation(); deleteCollection('${col.id}')" title="Delete Collection" class="h-6 w-6 rounded bg-darkPanel border border-darkBorder/60 flex items-center justify-center text-gray-400 hover:text-red-400 hover:border-red-500/30 transition">
                            <i data-lucide="trash-2" class="h-3.5 w-3.5"></i>
                        </button>
                    </div>
                    <div class="flex items-center gap-3">
                        <div class="h-8.5 w-8.5 rounded-lg bg-darkBorder flex items-center justify-center shrink-0 text-gray-400 ${isActive ? 'text-brand-400 bg-brand-500/10' : ''}">
                            <i data-lucide="folders" class="h-4 w-4"></i>
                        </div>
                        <p ondblclick="event.stopPropagation(); editCollection('${col.id}')" title="Double-click to edit collection" class="text-xs font-semibold text-gray-200 truncate pr-8 cursor-pointer">${col.name}</p>
                    </div>
                </div>
            `;
        }).join("");
        lucide.createIcons();
    }

    async function selectCollection(id) {
        if (typeof currentChatController !== 'undefined' && currentChatController) {
            // currentChatController.abort(); // Removed to allow background generation
            currentChatController = null;
        }
        window.activeCollectionId = id;
        activeFileId = null;
        localStorage.setItem('contextiq_active_type', 'collection');
        localStorage.setItem('contextiq_active_id', id);
        renderCollectionsList();
        const citationsSidebar = document.getElementById("citations-sidebar");
        if (citationsSidebar) citationsSidebar.classList.add("hidden");
        const rr1 = document.getElementById("right-resizer");
        if (rr1) rr1.classList.add("hidden");
        const citationsSidebarContent = document.getElementById("citations-sidebar-content");
        if (citationsSidebarContent) citationsSidebarContent.innerHTML = '<div class="text-center py-12 text-gray-500 select-none"><i data-lucide="info" class="h-8 w-8 mx-auto mb-2 text-gray-600"></i><p class="text-xs text-gray-400 px-4">No sources yet. Ask a question to retrieve grounded citations.</p></div>';
        
        try {
            const res = await fetch(`${API_BASE}/collections/${id}/files`);
            const colFiles = await res.json();
            if(colFiles.length === 0) {
                let options = `<option value="">-- Choose an uploaded document --</option>`;
                if (typeof files !== 'undefined') {
                    options += files.map(f => `<option value="${f.id}">${f.filename}</option>`).join("");
                }

                chatFeed.innerHTML = `
                    <div class="h-full flex flex-col items-center justify-center text-center p-8">
                        <div class="h-16 w-16 rounded-2xl bg-darkPanel/50 border border-darkBorder flex items-center justify-center mb-4">
                            <i data-lucide="folder-plus" class="h-8 w-8 text-gray-500"></i>
                        </div>
                        <h3 class="text-lg font-bold text-gray-200 mb-2">Empty Collection</h3>
                        <p class="text-sm text-gray-500 max-w-sm mb-6">Drag and drop documents from the "Documents" tab onto this collection in the sidebar, or add one below:</p>
                        
                        <div class="flex flex-col items-center gap-2 max-w-md w-full mt-2">
                            <div id="manual-add-file" class="w-full bg-darkPanel border border-darkBorder/80 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-brand-500/50 text-gray-200 overflow-y-auto max-h-32 text-left space-y-1">
                                ${typeof files !== 'undefined' ? files.map(f => `<label class="flex items-center space-x-2 cursor-pointer hover:bg-white/5 p-1 rounded"><input type="checkbox" value="${f.id}" class="manual-checkbox rounded border-gray-600 text-brand-500 focus:ring-brand-500 bg-darkBg"><span class="truncate">${f.filename}</span></label>`).join("") : ""}
                            </div>
                            <button onclick="manualAddFileToCollection('${id}')" class="w-full px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-xs font-semibold transition mt-1">Add Selected</button>
                        </div>
                    </div>
                `;
                lucide.createIcons();
                toggleInputState(false);
                chatHeader.classList.remove("hidden");
                const currentCollection = collections.find(c => c.id === id);
                const colName = currentCollection ? currentCollection.name : "Collection";
                activeFileTitle.innerHTML = `<i data-lucide="folders" class="h-4 w-4 text-brand-400"></i> <span ondblclick="editCollection('${id}')" class="font-bold text-white tracking-wide truncate max-w-sm cursor-pointer hover:text-brand-300 transition" title="Double-click to edit collection">${colName}</span>`;
                lucide.createIcons();
                blankSlate.classList.add("hidden");
                chatInputBar.classList.remove("hidden");
                return;
            }
            
            toggleInputState(false);
            chatFeed.innerHTML = `<div class="p-8 text-center"><i data-lucide="loader-2" class="h-6 w-6 animate-spin mx-auto text-brand-500 mb-3"></i><p class="text-sm text-gray-400 animate-pulse">Retrieving collection workspace...</p></div>`;
            lucide.createIcons();
            
            chatHeader.classList.remove("hidden");
            document.getElementById("btn-delete-file").classList.add("hidden");
            document.getElementById("btn-add-file-to-context").classList.add("hidden");
            document.getElementById("btn-view-collection-files").classList.remove("hidden");
            const currentCollection = collections.find(c => c.id === id);
            const colName = currentCollection ? currentCollection.name : "Collection";
            activeFileTitle.innerHTML = `<i data-lucide="folders" class="h-4 w-4 text-brand-400"></i> <span ondblclick="editCollection('${id}')" class="font-bold text-white tracking-wide truncate max-w-sm cursor-pointer hover:text-brand-300 transition" title="Double-click to edit collection">${colName}</span>`;
            lucide.createIcons();
            blankSlate.classList.add("hidden");
            chatInputBar.classList.remove("hidden");

            const msgsRes = await fetch(`${API_BASE}/collections/${id}/messages`);
            if(msgsRes.ok) {
                const data = await msgsRes.json();
                chatFeed.innerHTML = "";
                if (data.messages.length === 0) {
                    chatFeed.innerHTML = `<div id="blank-slate" class="h-full flex flex-col items-center justify-center text-center p-8 select-none"><div class="h-16 w-16 rounded-2xl bg-brand-500/10 border border-brand-500/20 flex items-center justify-center mb-6"><i data-lucide="folders" class="h-8 w-8 text-brand-400"></i></div><h3 class="text-xl font-bold text-white mb-2">Collection Workspace</h3><p class="text-sm text-gray-400 max-w-sm mb-8 leading-relaxed">Ask anything. The AI will retrieve matching chunks from all documents in this collection simultaneously.</p></div>`;
                    lucide.createIcons();
                } else {
                    data.messages.forEach(msg => {
                        appendMessageBubble(msg.role, msg.content, msg.sources, false, msg.id);
                    });
                }
                toggleInputState(false);
                if (window.activeGenerations && window.activeGenerations[id]) {
                    const b = appendMessageBubble('assistant', '<div class="flex items-center gap-2 text-brand-400"><span class="h-2 w-2 rounded-full bg-brand-400 animate-pulse"></span> Generating response in background... Please wait.</div>', null, true);
                    const cd = b.querySelector('.message-content');
                    if(cd) cd.classList.remove('typing-cursor');
                }
                scrollToBottom();
            }
            
        } catch(e) { 
            console.error(e); 
            alert("Error in selectCollection: " + e.message + "\nPlease take a screenshot of this error!");
            chatFeed.innerHTML = `<div class="p-8 text-center text-red-400">Failed to load collection. Error: ${e.message}</div>`;
        }
    }
    window.selectCollection = selectCollection;

    async function addDraggedFileToCollection(collectionId) {
        if(!draggedFileId) return;
        try {
            const res = await fetch(`${API_BASE}/collections/${collectionId}/files`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ file_id: draggedFileId })
            });
            if(res.ok) {
                showToast("Added to Collection", "Document added successfully", "success");
                if(window.activeCollectionId === collectionId) selectCollection(collectionId);
            } else {
                const err = await res.json();
                showToast("Error", err.detail || "Failed to add file", "error");
            }
        } catch(e) { console.error(e); }
        draggedFileId = null;
    }
    window.addDraggedFileToCollection = addDraggedFileToCollection;

    async function manualAddFileToCollection(collectionId) {
        const checkboxes = document.querySelectorAll('.manual-checkbox:checked');
        if(!checkboxes || checkboxes.length === 0) {
            showToast("Error", "Please select at least one document first", "error");
            return;
        }
        
        const selectedIds = Array.from(checkboxes).map(cb => cb.value).filter(val => val !== "");
        if (selectedIds.length === 0) return;

        let successCount = 0;
        for (const fileId of selectedIds) {
            try {
                const res = await fetch(`${API_BASE}/collections/${collectionId}/files`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ file_id: fileId })
                });
                if(res.ok) {
                    successCount++;
                } else {
                    const err = await res.json();
                    showToast("Error", err.detail || "Failed to add file", "error");
                }
            } catch(e) { console.error(e); }
        }
        
        if (successCount > 0) {
            showToast("Added to Collection", `${successCount} document(s) added successfully`, "success");
            if(window.activeCollectionId === collectionId) selectCollection(collectionId);
        }
    }
    window.manualAddFileToCollection = manualAddFileToCollection;
    
    // Override message submission logic safely
    document.getElementById("chat-form").addEventListener("submit", async function(e) {
        if(window.activeCollectionId) {
            e.preventDefault();
            e.stopImmediatePropagation();
            
            const query = userInput.value.trim();
            const activeGenId = window.activeCollectionId || activeFileId;
            window.activeGenerations[activeGenId] = true;
            const submittedGenId = activeGenId;
            if (!query) return;

            const userMsgId = Date.now().toString();
            appendMessageBubble("user", query, null, false, userMsgId);
            userInput.value = "";
            userInput.style.height = "38px";
            toggleInputState(true);
            scrollToBottom();

            const botMsgId = "msg-" + Date.now();
            const assistantBubble = appendMessageBubble("assistant", "", null, true, botMsgId);
            const contentDiv = assistantBubble.querySelector(".message-content");
            contentDiv.innerHTML = `<div class="flex flex-col gap-2 text-sm text-gray-400"><div class="flex items-center gap-2"><span class="h-2 w-2 rounded-full bg-brand-400 animate-pulse"></span>Retrieving relevant document chunks...</div></div>`;

            try {
                const provider = document.getElementById("llm-provider").value;
                const topK = parseInt(document.getElementById("rag-top-k").value) || 5;

                currentChatController = new AbortController();
                const response = await fetch(`${API_BASE}/collections/${window.activeCollectionId}/chat`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    signal: currentChatController.signal,
                    body: JSON.stringify({ query: query, provider: provider, top_k: topK })
                });

                if (!response.ok) throw new Error("API failed");
                
                const reader = response.body.getReader();
                const decoder = new TextDecoder("utf-8");
                let done = false;
                let fullText = "";

                while (!done) {
                    const { value, done: readerDone } = await reader.read();
                    done = readerDone;
                    if (value) {
                        const chunk = decoder.decode(value, { stream: true });
                        const lines = chunk.split("\n");
                        let eventType = null;

                        for (const line of lines) {
                            if (line.startsWith("event: ")) {
                                eventType = line.substring(7).trim();
                            } else if (line.startsWith("data: ")) {
                                const dataStr = line.substring(6).trim();
                                if (dataStr === "[DONE]") { done = true; break; }
                                try {
                                    const parsed = JSON.parse(dataStr);
                                    if (eventType === "sources") {
                                        // skip sources
                                    } else if (eventType === "token") {
                                        fullText += parsed;
                                        contentDiv.innerHTML = marked.parse(fullText);
                                    }
                                } catch (e) {}
                            }
                        }
                    }
                }
            } catch (err) {
                if (err.name === 'AbortError') {
                    contentDiv.innerHTML += `<div class="mt-4 text-xs font-semibold text-gray-500 flex items-center gap-1.5"><i data-lucide="square" class="h-3 w-3 fill-current"></i> Generation stopped by user.</div>`;
                } else {
                    contentDiv.innerHTML = `<span class="text-rose-400">Failed to get response: ${err.message}</span>`;
                }
            } finally {
                delete window.activeGenerations[submittedGenId];
                const currentActiveId = window.activeCollectionId || activeFileId;
                if (currentActiveId === submittedGenId) {
                    currentChatController = null;
                    toggleInputState(false);
                    Prism.highlightAll();
                    if (window.activeCollectionId) {
                        if (typeof selectCollection === 'function') selectCollection(window.activeCollectionId);
                    } else if (activeFileId) {
                        selectWorkspace(activeFileId, 'ready');
                    }
                } else if (currentActiveId) {
                    showToast('Background Task Finished', 'A background response has finished generating.', 'success');
                }
            }
        }
    }, true);

    let activeModalCollectionId = null;

    // --- COLLECTION FILES MODAL ---
    window.openCollectionFilesModal = async function(colId) {
        const targetId = (typeof colId === 'string' && colId.trim() !== '') ? colId : window.activeCollectionId;
        if (!targetId) return;
        activeModalCollectionId = targetId;
        
        const modal = document.getElementById("collection-files-modal");
        const listDiv = document.getElementById("collection-files-list");
        const nameInput = document.getElementById("modal-collection-name");
        const saveBtn = document.getElementById("modal-save-name-btn");
        
        // Setup name input
        const targetCol = collections.find(c => c.id === targetId);
        if (targetCol && nameInput) {
            nameInput.value = targetCol.name;
            saveBtn.classList.add("hidden");
            
            // Show save button on edit
            nameInput.oninput = function() {
                if (nameInput.value.trim() !== targetCol.name && nameInput.value.trim() !== "") {
                    saveBtn.classList.remove("hidden");
                } else {
                    saveBtn.classList.add("hidden");
                }
            };
            
            // Enter key to save
            nameInput.onkeydown = function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    if (!saveBtn.classList.contains("hidden")) {
                        window.saveModalCollectionName();
                    }
                }
            };
        }
        
        listDiv.innerHTML = `<div class="p-8 text-center"><i data-lucide="loader-2" class="h-6 w-6 animate-spin mx-auto text-brand-500 mb-3"></i><p class="text-sm text-gray-400">Loading files...</p></div>`;
        lucide.createIcons();
        
        modal.classList.remove("hidden");
        modal.classList.add("flex");
        
        try {
            const res = await fetch(`${API_BASE}/collections/${targetId}/files`);
            const filesData = await res.json();
            
            if (filesData.length === 0) {
                listDiv.innerHTML = `<p class="text-gray-400 text-center py-4">No files in this collection.</p>`;
                return;
            }
            
            let html = '<div class="flex flex-col gap-2">';
            for(const f of filesData) {
                html += `
                    <div class="flex items-center justify-between p-3 glass-card rounded-lg border border-darkBorder/50 group">
                        <div class="flex items-center gap-3">
                            <i data-lucide="file-text" class="h-4 w-4 text-brand-400"></i>
                            <div>
                                <p class="text-sm text-white font-medium">${f.filename}</p>
                                <p class="text-[10px] text-gray-500">Status: ${f.status}${(f.status === "ready" && !["csv", "excel"].includes(f.file_type)) ? ` (${f.graph_ready ? 'Graph Ready' : 'Graph Building...'})` : ''} | Size: ${(f.file_size/1024).toFixed(0)} KB</p>
                            </div>
                        </div>
                        <button onclick="window.removeFileFromCollection('${f.id}', '${targetId}')" class="p-2 rounded-lg hover:bg-red-500/10 text-gray-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition" title="Remove from Collection">
                            <i data-lucide="trash-2" class="h-4 w-4"></i>
                        </button>
                    </div>
                `;
            }
            html += '</div>';
            listDiv.innerHTML = html;
            lucide.createIcons();
        } catch(e) {
            listDiv.innerHTML = `<p class="text-red-400 text-center py-4">Error loading files.</p>`;
        }
    };
    
    window.closeCollectionFilesModal = function() {
        const modal = document.getElementById("collection-files-modal");
        modal.classList.add("hidden");
        modal.classList.remove("flex");
        const container = document.getElementById("modal-add-existing-container");
        if (container) {
            container.classList.add("hidden");
            container.classList.remove("flex");
        }
    };

    window.toggleModalAddExisting = function() {
        const container = document.getElementById("modal-add-existing-container");
        if (container.classList.contains("hidden")) {
            container.classList.remove("hidden");
            container.classList.add("flex");
            // Populate the checkboxes
            const selectEl = document.getElementById("modal-add-existing-file");
            if (typeof files !== 'undefined') {
                selectEl.innerHTML = files.map(f => `<label class="flex items-center space-x-2 cursor-pointer hover:bg-white/5 p-1.5 rounded"><input type="checkbox" value="${f.id}" class="modal-checkbox rounded border-gray-600 text-brand-500 focus:ring-brand-500 bg-darkBg"><span class="truncate">${f.filename}</span></label>`).join("");
                // Make it look like a scrollable list instead of a select
                selectEl.outerHTML = `<div id="modal-add-existing-file" class="w-full bg-darkBg border border-darkBorder rounded-lg px-3 py-2 text-xs text-gray-200 overflow-y-auto max-h-48 text-left space-y-1">${selectEl.innerHTML}</div>`;
            }
        } else {
            container.classList.add("hidden");
            container.classList.remove("flex");
        }
    };

    window.submitModalAddExisting = async function() {
        if (!activeModalCollectionId) return;
        const checkboxes = document.querySelectorAll('.modal-checkbox:checked');
        if(!checkboxes || checkboxes.length === 0) {
            showToast("Error", "Please select at least one document first", "error");
            return;
        }
        
        const selectedIds = Array.from(checkboxes).map(cb => cb.value).filter(val => val !== "");
        if (selectedIds.length === 0) return;

        showToast("Adding", `Adding ${selectedIds.length} document(s)...`, "success");

        let successCount = 0;
        for (const fileId of selectedIds) {
            try {
                const res = await fetch(`${API_BASE}/collections/${activeModalCollectionId}/files`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ file_id: fileId })
                });
                if(res.ok) {
                    successCount++;
                } else {
                    const err = await res.json();
                    showToast("Error", err.detail || "Failed to add file", "error");
                }
            } catch(e) { console.error(e); }
        }
        
        if (successCount > 0) {
            showToast("Added to Collection", `${successCount} document(s) added successfully`, "success");
            window.toggleModalAddExisting();
            window.openCollectionFilesModal(activeModalCollectionId);
            if (activeModalCollectionId === window.activeCollectionId) {
                selectCollection(window.activeCollectionId);
            }
        }
    };

    window.saveModalCollectionName = async function() {
        if (!activeModalCollectionId) return;
        const nameInput = document.getElementById("modal-collection-name");
        const saveBtn = document.getElementById("modal-save-name-btn");
        const newName = nameInput.value.trim();
        if (!newName) return;
        
        saveBtn.innerText = "Saving...";
        try {
            const res = await fetch(`${API_BASE}/collections/${activeModalCollectionId}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name: newName })
            });
            if (res.ok) {
                await fetchCollections();
                saveBtn.classList.add("hidden");
                saveBtn.innerText = "Save Name";
                
                // Update header if this is the active one
                if (activeModalCollectionId === window.activeCollectionId) {
                    const activeFileTitle = document.getElementById("active-file-title");
                    if (activeFileTitle) {
                        activeFileTitle.innerHTML = `<i data-lucide="folders" class="h-4 w-4 text-brand-400"></i> <span ondblclick="openCollectionFilesModal('${window.activeCollectionId}')" class="font-bold text-white tracking-wide truncate max-w-sm cursor-pointer hover:text-brand-300 transition" title="Double-click to edit collection">${newName}</span>`;
                        lucide.createIcons();
                    }
                }
            } else {
                const err = await res.json();
                showToast("Error", err.detail || "Failed to rename collection", "error");
                saveBtn.innerText = "Save Name";
            }
        } catch (e) {
            console.error(e);
            showToast("Error", "An unexpected error occurred", "error");
            saveBtn.innerText = "Save Name";
        }
    };

    window.removeFileFromCollection = async function(fileId, colId) {
        const targetId = colId || window.activeCollectionId;
        if (!targetId) return;
        if(!confirm("Remove this document from the collection?")) return;
        try {
            const res = await fetch(`${API_BASE}/collections/${targetId}/files/${fileId}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                showToast("File Removed", "File removed from collection.", "success");
                // Refresh the modal
                window.openCollectionFilesModal(targetId);
                if (targetId === window.activeCollectionId) {
                    selectCollection(window.activeCollectionId);
                }
            } else {
                showToast("Error", "Could not remove file.", "error");
            }
        } catch(err) {
            console.error(err);
            showToast("Error", "Could not remove file.", "error");
        }
    };
    
    window.uploadFileToCollection = async function(event) {
        const fileInput = event.target;
        const files = Array.from(fileInput.files);
        if (files.length === 0 || !activeModalCollectionId) return;

        showToast("Uploading", `Uploading ${files.length} file(s) to collection...`, "info");
        
        // Reset input so the same file can be selected again
        fileInput.value = "";

        const isCurrentlyActive = (window.activeCollectionId === activeModalCollectionId);

        const uploadPromises = files.map(async (file) => {
            const formData = new FormData();
            formData.append("file", file);
            formData.append("collection_id", activeModalCollectionId);

            try {
                const response = await fetch(`${API_BASE}/files/upload`, {
                    method: "POST",
                    body: formData
                });

                if (response.ok) {
                    showToast("Success", `"${file.name}" uploaded successfully.`, "success");
                } else {
                    const error = await response.json();
                    showToast("Upload Failed", `"${file.name}": ${error.detail || "Unknown error"}`, "error");
                }
            } catch (error) {
                console.error(error);
                showToast("Upload Failed", `"${file.name}": Network error occurred.`, "error");
            }
        });

        await Promise.all(uploadPromises);
        
        // Refresh modal and collection view
        if (typeof fetchFiles === 'function') fetchFiles(); // Refresh global files list too
        window.openCollectionFilesModal(activeModalCollectionId);
        if (isCurrentlyActive) {
            selectCollection(window.activeCollectionId); // Refresh main view
        }
    };

    window.triggerCollectionUpload = function(collectionId) {
        // Set context to the targeted collection
        window.activeCollectionId = collectionId;
        // Trigger the hidden file input
        document.getElementById('collection-upload-input').click();
    };

    // Global drag-and-drop specifically for Collections
    document.body.addEventListener("dragover", (e) => {
        if (window.activeCollectionId) {
            e.preventDefault(); // Allow drop
        }
    }, false);

    document.body.addEventListener("drop", async (e) => {
        if (window.activeCollectionId) {
            const dropZone = document.getElementById("drop-zone");
            if (dropZone && dropZone.contains(e.target)) {
                // Let the document dropzone handle it if dropped explicitly there
                return;
            }
            
            e.preventDefault();
            const dt = e.dataTransfer;
            if (dt && dt.files && dt.files.length > 0) {
                const files = Array.from(dt.files);
                showToast("Uploading", `Uploading ${files.length} file(s) to collection...`, "success");

                const uploadPromises = files.map(async (file) => {
                    const formData = new FormData();
                    formData.append("file", file);
                    formData.append("collection_id", window.activeCollectionId);

                    try {
                        const response = await fetch(`${API_BASE}/files/upload`, {
                            method: "POST",
                            body: formData
                        });

                        if (response.ok) {
                            showToast("Success", `"${file.name}" uploaded successfully.`, "success");
                        } else {
                            const error = await response.json();
                            showToast("Upload Failed", `"${file.name}": ${error.detail || "Unknown error"}`, "error");
                        }
                    } catch (error) {
                        console.error(error);
                        showToast("Upload Failed", `"${file.name}": Network error occurred.`, "error");
                    }
                });

                await Promise.all(uploadPromises);
                
                if (typeof fetchFiles === 'function') fetchFiles();
                selectCollection(window.activeCollectionId);
            }
        }
    }, false);
}
