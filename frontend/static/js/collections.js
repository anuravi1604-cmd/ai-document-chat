
// --- COLLECTIONS UI LOGIC ---
const tabDocs = document.getElementById("tab-docs");
const tabCollections = document.getElementById("tab-collections");
const docsContainer = document.getElementById("docs-container");
const collectionsContainer = document.getElementById("collections-container");
const collectionsList = document.getElementById("collections-list");

if (tabDocs && tabCollections) {
    let collections = [];
    let activeCollectionId = null;

    tabDocs.addEventListener("click", () => {
        tabDocs.classList.add("text-white", "border-brand-500");
        tabDocs.classList.remove("text-gray-500", "border-transparent");
        tabCollections.classList.remove("text-white", "border-brand-500");
        tabCollections.classList.add("text-gray-500", "border-transparent");
        docsContainer.classList.remove("hidden");
        collectionsContainer.classList.add("hidden");
        activeCollectionId = null;
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
                fetchCollections();
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
            if(activeCollectionId === id) {
                activeCollectionId = null;
                if(typeof renderChatState === 'function') renderChatState();
            }
            fetchCollections();
        } catch (e) { console.error(e); }
    }
    window.deleteCollection = deleteCollection;

    let draggedFileId = null;
    window.setDraggedFileId = function(id) { draggedFileId = id; }

    function renderCollectionsList() {
        if (collections.length === 0) {
            collectionsList.innerHTML = `<div class="text-center py-8 text-gray-500"><i data-lucide="folders" class="h-8 w-8 mx-auto mb-2 text-gray-600"></i><p class="text-xs">No collections created</p></div>`;
            lucide.createIcons();
            return;
        }

        collectionsList.innerHTML = collections.map(col => {
            const isActive = col.id === activeCollectionId;
            let itemClass = isActive ? "bg-gradient-to-tr from-brand-600/10 to-indigo-500/[0.03] border border-brand-500/25 shadow-lg shadow-brand-500/[0.02]" : "bg-darkPanel/40 hover:bg-darkPanel border border-darkBorder/40";
            
            return `
                <div 
                    onclick="selectCollection('${col.id}')"
                    ondragover="event.preventDefault(); this.classList.add('border-brand-500');"
                    ondragleave="this.classList.remove('border-brand-500');"
                    ondrop="event.preventDefault(); this.classList.remove('border-brand-500'); addDraggedFileToCollection('${col.id}')"
                    class="relative p-3.5 rounded-xl cursor-pointer transition flex flex-col group ${itemClass}">
                    <div class="absolute top-2.5 right-2.5 flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition z-20">
                        <button onclick="event.stopPropagation(); window.triggerCollectionUpload('${col.id}')" title="Upload File" class="h-6 w-6 rounded bg-darkPanel border border-darkBorder/60 flex items-center justify-center text-gray-400 hover:text-brand-400 hover:border-brand-500/30 transition">
                            <i data-lucide="plus" class="h-3.5 w-3.5"></i>
                        </button>
                        <button onclick="event.stopPropagation(); deleteCollection('${col.id}')" title="Delete Collection" class="h-6 w-6 rounded bg-darkPanel border border-darkBorder/60 flex items-center justify-center text-gray-400 hover:text-red-400 hover:border-red-500/30 transition">
                            <i data-lucide="trash-2" class="h-3.5 w-3.5"></i>
                        </button>
                    </div>
                    <div class="flex items-center gap-3">
                        <div class="h-8.5 w-8.5 rounded-lg bg-darkBorder flex items-center justify-center shrink-0 text-gray-400 ${isActive ? 'text-brand-400 bg-brand-500/10' : ''}">
                            <i data-lucide="folders" class="h-4 w-4"></i>
                        </div>
                        <p class="text-xs font-semibold text-gray-200 truncate pr-8">${col.name}</p>
                    </div>
                </div>
            `;
        }).join("");
        lucide.createIcons();
    }

    async function selectCollection(id) {
        activeCollectionId = id;
        activeFileId = null;
        renderCollectionsList();
        
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
                        
                        <div class="flex items-center gap-2 max-w-md w-full mt-2">
                            <select id="manual-add-file" class="flex-1 bg-darkPanel border border-darkBorder/80 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-brand-500/50 text-gray-200">
                                ${options}
                            </select>
                            <button onclick="manualAddFileToCollection('${id}')" class="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-xs font-semibold transition">Add</button>
                        </div>
                    </div>
                `;
                lucide.createIcons();
                toggleInputState(false);
                chatHeader.classList.remove("hidden");
                activeFileTitle.innerHTML = `<i data-lucide="folders" class="h-4 w-4 text-brand-400"></i> <span class="font-bold text-white tracking-wide">Collection</span>`;
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
            document.getElementById("btn-view-collection-files").classList.remove("hidden");
            activeFileTitle.innerHTML = `<i data-lucide="folders" class="h-4 w-4 text-brand-400"></i> <span class="font-bold text-white tracking-wide">Collection</span>`;
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
                if(activeCollectionId === collectionId) selectCollection(collectionId);
            }
        } catch(e) { console.error(e); }
        draggedFileId = null;
    }
    window.addDraggedFileToCollection = addDraggedFileToCollection;

    async function manualAddFileToCollection(collectionId) {
        const selectEl = document.getElementById('manual-add-file');
        if(!selectEl || !selectEl.value) {
            showToast("Error", "Please select a document first", "error");
            return;
        }
        const fileId = selectEl.value;
        try {
            const res = await fetch(`${API_BASE}/collections/${collectionId}/files`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ file_id: fileId })
            });
            if(res.ok) {
                showToast("Added to Collection", "Document added successfully", "success");
                if(activeCollectionId === collectionId) selectCollection(collectionId);
            }
        } catch(e) { console.error(e); }
    }
    window.manualAddFileToCollection = manualAddFileToCollection;
    
    // Override message submission logic safely
    document.getElementById("chat-form").addEventListener("submit", async function(e) {
        if(activeCollectionId) {
            e.preventDefault();
            e.stopImmediatePropagation();
            
            const query = userInput.value.trim();
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
                const response = await fetch(`${API_BASE}/collections/${activeCollectionId}/chat`, {
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
                currentChatController = null;
                toggleInputState(false);
                Prism.highlightAll();
            }
        }
    }, true);

    // --- COLLECTION FILES MODAL ---
    window.openCollectionFilesModal = async function() {
        if (!activeCollectionId) return;
        const modal = document.getElementById("collection-files-modal");
        const listDiv = document.getElementById("collection-files-list");
        
        listDiv.innerHTML = `<div class="p-8 text-center"><i data-lucide="loader-2" class="h-6 w-6 animate-spin mx-auto text-brand-500 mb-3"></i><p class="text-sm text-gray-400">Loading files...</p></div>`;
        lucide.createIcons();
        
        modal.classList.remove("hidden");
        modal.classList.add("flex");
        
        try {
            const res = await fetch(`${API_BASE}/collections/${activeCollectionId}/files`);
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
                                <p class="text-[10px] text-gray-500">Status: ${f.status} | Size: ${(f.file_size/1024).toFixed(0)} KB</p>
                            </div>
                        </div>
                        <button onclick="window.removeFileFromCollection('${f.id}')" class="p-2 rounded-lg hover:bg-red-500/10 text-gray-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition" title="Remove from Collection">
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
    };

    window.removeFileFromCollection = async function(fileId) {
        if (!activeCollectionId) return;
        if (!confirm("Are you sure you want to remove this file from the collection?")) return;
        
        try {
            const res = await fetch(`${API_BASE}/collections/${activeCollectionId}/files/${fileId}`, { method: "DELETE" });
            if (res.ok) {
                showToast("File Removed", "File removed from collection.", "success");
                // Refresh the modal
                window.openCollectionFilesModal();
            } else {
                showToast("Error", "Could not remove file.", "error");
            }
        } catch(err) {
            console.error(err);
            showToast("Error", "Could not remove file.", "error");
        }
    };
    
    window.uploadFileToCollection = async function(event) {
        if (!activeCollectionId) return;
        const fileInput = event.target;
        const file = fileInput.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append("file", file);
        formData.append("collection_id", activeCollectionId);

        showToast("Uploading", `Uploading ${file.name} to collection...`, "success");
        
        // Reset input so the same file can be selected again
        fileInput.value = "";

        try {
            const response = await fetch(`${API_BASE}/files/upload`, {
                method: "POST",
                body: formData
            });

            if (response.ok) {
                showToast("Success", "File uploaded and added to collection.", "success");
                // Refresh modal and collection view
                if (typeof fetchFiles === 'function') fetchFiles(); // Refresh global files list too
                window.openCollectionFilesModal();
                selectCollection(activeCollectionId); // Refresh main view
            } else {
                const error = await response.json();
                showToast("Upload Failed", error.detail || "Unknown error", "error");
            }
        } catch (error) {
            console.error(error);
            showToast("Upload Failed", "Network error occurred.", "error");
        }
    };

    window.triggerCollectionUpload = function(collectionId) {
        // Set context to the targeted collection
        activeCollectionId = collectionId;
        // Trigger the hidden file input
        document.getElementById('collection-upload-input').click();
    };

    // Global drag-and-drop specifically for Collections
    document.body.addEventListener("dragover", (e) => {
        if (activeCollectionId) {
            e.preventDefault(); // Allow drop
        }
    }, false);

    document.body.addEventListener("drop", async (e) => {
        if (activeCollectionId) {
            const dropZone = document.getElementById("drop-zone");
            if (dropZone && dropZone.contains(e.target)) {
                // Let the document dropzone handle it if dropped explicitly there
                return;
            }
            
            e.preventDefault();
            const dt = e.dataTransfer;
            if (dt && dt.files && dt.files.length > 0) {
                const file = dt.files[0];
                const formData = new FormData();
                formData.append("file", file);
                formData.append("collection_id", activeCollectionId);

                showToast("Uploading", `Uploading ${file.name} to collection...`, "success");

                try {
                    const response = await fetch(`${API_BASE}/files/upload`, {
                        method: "POST",
                        body: formData
                    });

                    if (response.ok) {
                        showToast("Success", "File uploaded to collection.", "success");
                        if (typeof fetchFiles === 'function') fetchFiles();
                        selectCollection(activeCollectionId);
                    } else {
                        const error = await response.json();
                        showToast("Upload Failed", error.detail || "Unknown error", "error");
                    }
                } catch (error) {
                    console.error(error);
                    showToast("Upload Failed", "Network error occurred.", "error");
                }
            }
        }
    }, false);
}
