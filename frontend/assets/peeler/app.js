(function () {
  const api = window.PaperLensAPI;

  /* ── Demo mode: pre-built AIAYN peel (no API call, no credits) ── */
  function getDemoThreadData() {
    return {
      thread: { thread_id: 'demo-thread-aiayn', paper_id: 'arxiv:1706.03762', title: 'Attention Is All You Need' },
      paper: {
        canonical_id: 'arxiv:1706.03762', source_type: 'arxiv',
        title: 'Attention Is All You Need',
        authors: ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'Jakob Uszkoreit'],
        abstract: 'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. On WMT 2014 English-to-German translation, the big Transformer outperforms all previously published models by more than 2 BLEU.',
        arxiv_id: '1706.03762', published_at: '2017-06-12', topic: 'LLMs', difficulty: 'Intermediate', confidence: 'high'
      },
      peel: {
        paper_id: 'arxiv:1706.03762', schema_version: '1.0', model_used: 'demo-cached', completed_from_cache: true,
        sections: {
          what: { title: 'What this paper does', confidence: 'high', body: 'The Transformer (Vaswani et al., 2017) is a sequence-to-sequence model that completely removes recurrence and convolution, relying entirely on attention mechanisms.\n\nBefore this paper, state-of-the-art models used RNNs/LSTMs which process tokens sequentially — slow to train and hard to parallelize. The Transformer computes attention over all positions simultaneously using Scaled Dot-Product Attention.\n\nThe architecture has an Encoder (6 layers) and Decoder (6 layers). Each layer has Multi-Head Self-Attention + Position-wise Feed-Forward Network, with residual connections and layer normalization. Positional encodings (sine/cosine) are added to embeddings so the model knows token order.\n\nResults: 28.4 BLEU on WMT 2014 EN-DE, 41.0 BLEU on EN-FR. Trained in 12h on 8 P100 GPUs — dramatically faster than prior models.', evidence: [{label:'Abstract', text:'a new simple network architecture, the Transformer, based solely on attention mechanisms', location:'Abstract'}] },
          timeline: { title: 'What came before', confidence: 'high', body: 'Seq2Seq (Sutskever et al., 2014) showed LSTM encoder-decoders could translate sentences. Attention (Bahdanau et al., 2015) improved this by letting the decoder attend to all encoder states. ConvS2S (Gehring et al., 2017) used CNNs for parallelization but had limited receptive field for long-range dependencies.\n\nThe key limitation: RNNs have O(n) sequential operations — you cannot parallelize across time steps. Training a 6-layer LSTM on 12M sentences takes days.\n\nWhich is precisely where this paper enters.', evidence: [{label:'Introduction', text:'Recurrent neural networks have been firmly established as state of the art in sequence modeling', location:'Introduction'}] },
          fixes: { title: 'What this paper fixes', confidence: 'high', body: 'The fundamental fix: replace sequential computation with parallel attention. The Transformer uses O(1) sequential operations instead of O(n) for RNNs.\n\nMulti-Head Attention directly models relationships between any two positions in O(1) layers. RNNs need O(n) layers for long-range dependencies. Running 8 parallel attention heads captures different relationship types simultaneously.', evidence: [{label:'Model', text:'Multi-head attention allows the model to jointly attend to information from different representation subspaces', location:'Section 3.2'}] },
          architecture: { title: 'How the architecture works', confidence: 'high', body: 'Input tokens → embeddings + positional encoding → Encoder (6×[Self-Attention + FFN]) → Decoder (6×[Masked Self-Attention + Cross-Attention + FFN]) → Linear + Softmax.\n\nScaled Dot-Product Attention: Attention(Q,K,V) = softmax(QK^T/√d_k)V. Multi-Head runs 8 of these in parallel on projected Q,K,V subspaces, concatenates, projects back.\n\nPosition-wise FFN: FFN(x) = max(0,xW₁+b₁)W₂+b₂ — d_model=512, d_ff=2048. Residual + LayerNorm wraps each sub-layer.', evidence: [{label:'Section 3', text:'The encoder maps an input sequence to a sequence of continuous representations', location:'Section 3'}] },
          results: { title: 'Results and benchmarks', confidence: 'high', body: 'WMT 2014 EN-DE: 28.4 BLEU (+2 over prior SOTA). WMT 2014 EN-FR: 41.0 BLEU (new single-model record). Training: 3.5 days on 8 P100 GPUs — 3.3×10^18 FLOPs, less than prior SOTA. Ablations: reducing heads from 8→1 costs 0.9 BLEU; reducing d_k hurts; larger models consistently better.', evidence: [{label:'Results', text:'outperforms the best previously reported models by more than 2.0 BLEU', location:'Section 6'}] },
          verdict: { title: 'Should you care', confidence: 'high', body: 'YES — this is the foundation of all modern AI. GPT, BERT, T5, LLaMA, Gemini, Claude — all Transformers. If you do AI/ML, NLP, vision, or protein folding, this is required reading.\n\nLimitation: O(n²) memory/compute in sequence length. Addressed by efficient attention variants (Longformer, FlashAttention). Not ideal for very long sequences without modifications.', evidence: [{label:'Conclusion', text:'the first sequence transduction model based entirely on attention', location:'Conclusion'}] }
        },
        architecture: {
          nodes: [
            {id:'input_embed', label:'Input Embedding + Positional Encoding', type:'input'},
            {id:'encoder', label:'Encoder Stack (N=6 layers)', type:'module'},
            {id:'multihead_attn', label:'Multi-Head Attention (h=8)', type:'attention'},
            {id:'ffn', label:'Position-wise FFN', type:'module'},
            {id:'decoder', label:'Decoder Stack (N=6 layers)', type:'module'},
            {id:'output', label:'Linear + Softmax', type:'output'}
          ],
          edges: [
            {from:'input_embed', to:'encoder'}, {from:'encoder', to:'multihead_attn'},
            {from:'multihead_attn', to:'ffn'}, {from:'ffn', to:'decoder'}, {from:'decoder', to:'output'}
          ],
          reveal_order: ['input_embed','encoder','multihead_attn','ffn','decoder','output'],
          node_explanations: {
            input_embed: 'Token embeddings (d=512) + sinusoidal positional encodings. Gives both meaning and position.',
            encoder: '6 identical layers: Multi-Head Self-Attention + FFN + residual + LayerNorm. Processes all positions in parallel.',
            multihead_attn: '8 parallel attention heads on projected Q,K,V subspaces. Captures different relationship types simultaneously.',
            ffn: 'Two linear layers with ReLU: d_model=512 → d_ff=2048 → d_model=512. Applied independently per position.',
            decoder: '6 layers with masked self-attn + cross-attention over encoder output + FFN. Generates tokens auto-regressively.',
            output: 'Linear projection to vocab size + softmax. Produces token probabilities.'
          },
          data_flow_steps: [
            'Input tokens → 512-dim embeddings', 'Positional encodings added', 'Encoder processes all positions in parallel',
            'Each of 8 heads computes Attention(Q,K,V) = softmax(QKᵀ/√d_k)V', 'FFN applied position-wise',
            'Decoder attends to encoder output (cross-attention)', 'Linear + softmax → token probabilities'
          ],
          expanded_nodes: [
            {id:'encoder.self_attn', label:'Multi-Head Self-Attention', type:'attention'},
            {id:'encoder.add_norm1', label:'Add & Norm', type:'normalization'},
            {id:'encoder.ffn_layer', label:'Feed-Forward (512→2048→512)', type:'module'},
            {id:'encoder.add_norm2', label:'Add & Norm', type:'normalization'},
            {id:'multihead_attn.qkv', label:'Q, K, V Linear Projections', type:'module'},
            {id:'multihead_attn.sdp', label:'Scaled Dot-Product Attention', type:'attention'},
            {id:'multihead_attn.concat', label:'Concat + Output Projection', type:'module'}
          ],
          expanded_edges: [
            {from:'encoder.self_attn', to:'encoder.add_norm1'}, {from:'encoder.add_norm1', to:'encoder.ffn_layer'},
            {from:'encoder.ffn_layer', to:'encoder.add_norm2'},
            {from:'multihead_attn.qkv', to:'multihead_attn.sdp'}, {from:'multihead_attn.sdp', to:'multihead_attn.concat'}
          ],
          expansion_map: {
            encoder: ['encoder.self_attn','encoder.add_norm1','encoder.ffn_layer','encoder.add_norm2'],
            multihead_attn: ['multihead_attn.qkv','multihead_attn.sdp','multihead_attn.concat']
          }
        },
        math_peel: [
          { latex: 'Attention(Q,K,V) = softmax\\left(\\frac{QK^T}{\\sqrt{d_k}}\\right)V', location: 'Section 3.2',
            symbols: [{symbol:'Q', meaning:'Query — what we look for'}, {symbol:'K', meaning:'Key — what each token offers'}, {symbol:'V', meaning:'Value — content to retrieve'}, {symbol:'d_k', meaning:'Key dimension (64) — scaling factor'}],
            plain_meaning: 'Each query scores every key via dot product, scaled by sqrt(d_k) to prevent gradient saturation, then softmax weights the values. This is how tokens attend to each other.',
            role_in_architecture: 'Core computation in every Multi-Head Attention layer (encoder + decoder).',
            behavior_if_changed: 'Removing sqrt(d_k) scaling causes dot products to grow large, pushing softmax into saturation with near-zero gradients — training fails.', evidence: [] },
          { latex: 'MultiHead(Q,K,V) = Concat(head_1,\\ldots,head_h)W^O', location: 'Section 3.2',
            symbols: [{symbol:'head_i', meaning:'i-th attention head output'}, {symbol:'W^O', meaning:'Output projection matrix'}, {symbol:'h', meaning:'Number of heads (h=8)'}],
            plain_meaning: 'Run 8 separate attention operations in parallel on projected Q,K,V, concatenate, project back. Allows attending to multiple relationship types simultaneously.',
            role_in_architecture: 'The attention sub-layer in every encoder and decoder layer.',
            behavior_if_changed: 'Using h=1 drops EN-DE BLEU by 0.9 — the model loses ability to capture multiple types of relationships.', evidence: [] },
          { latex: 'PE_{(pos,2i)} = \\sin\\left(\\frac{pos}{10000^{2i/d_{model}}}\\right)', location: 'Section 3.5',
            symbols: [{symbol:'pos', meaning:'Token position in sequence'}, {symbol:'i', meaning:'Dimension index'}, {symbol:'d_{model}', meaning:'Embedding dimension (512)'}],
            plain_meaning: 'Each embedding dimension gets a sinusoidal wave of a different frequency. Gives the model a smooth, continuous representation of position that generalizes to unseen sequence lengths.',
            role_in_architecture: 'Added to token embeddings at the Input Embedding stage.',
            behavior_if_changed: 'Without positional encoding, all token positions are equivalent — the model cannot learn word order, destroying translation quality.', evidence: [] },
          { latex: 'FFN(x) = \\max(0, xW_1 + b_1)W_2 + b_2', location: 'Section 3.3',
            symbols: [{symbol:'x', meaning:'Input from attention layer'}, {symbol:'W_1,b_1', meaning:'First projection: d_model→d_ff=2048'}, {symbol:'W_2,b_2', meaning:'Second projection: d_ff→d_model'}, {symbol:'\\max(0,\\cdot)', meaning:'ReLU non-linearity'}],
            plain_meaning: 'Two linear layers with ReLU: expands to 2048 then back to 512. Adds non-linearity and position-specific computation after attention.',
            role_in_architecture: 'Second sub-layer in every encoder and decoder layer.',
            behavior_if_changed: 'Removing FFN or shrinking d_ff substantially hurts quality — the FFN provides critical non-linear processing capacity.', evidence: [] }
        ],
        related_papers: [
          { title: 'Neural Machine Translation by Jointly Learning to Align and Translate', year: 2015, authors: ['Bahdanau', 'Cho', 'Bengio'], source_id: 'arxiv:1409.0473', summary: 'Introduced attention for RNNs: decoder learns to softly attend to different encoder states.', what_it_tried: 'Context vector as weighted sum of encoder states.', limitation: 'Still sequential RNNs — cannot parallelize.', connection_to_this_paper: 'The Transformer generalizes this to be the entire architecture, no RNNs at all.' },
          { title: 'Sequence to Sequence Learning with Neural Networks', year: 2014, authors: ['Sutskever', 'Vinyals', 'Le'], source_id: 'arxiv:1409.3215', summary: 'LSTM encoder-decoder for variable-length sequences. Enabled neural machine translation.', what_it_tried: 'Encode entire input to fixed vector, decode to output.', limitation: 'Fixed-size context vector is a bottleneck for long sequences.', connection_to_this_paper: 'Transformer keeps encoder-decoder but uses attention instead of fixed context vector.' },
          { title: 'Convolutional Sequence to Sequence Learning', year: 2017, authors: ['Gehring', 'Auli', 'Grangier', 'Dauphin'], source_id: 'arxiv:1705.03122', summary: 'CNN-based seq2seq for full training parallelization.', what_it_tried: 'CNNs instead of RNNs for parallel training.', limitation: 'Limited receptive field — long-range dependencies require many layers.', connection_to_this_paper: 'Transformer achieves same parallelization but every token attends to every other in O(1) layers.' }
        ],
        suggested_questions: [
          'Why does scaling by sqrt(d_k) prevent gradient issues?',
          'How does Multi-Head Attention capture different relationship types?',
          'What made the Transformer possible to train in parallel?',
          'Why did this paper make GPT and BERT possible?'
        ]
      },
      messages: []
    };
  }

  const STAGES = [
    ["resolve",      "Lens calibration",      "Locking onto the paper identity"],
    ["extract",      "Page layer peel",        "Separating abstract, method, tables, and references"],
    ["index",        "Chunk tiles",            "Indexing the paper into searchable knowledge pieces"],
    ["history",      "Timeline links",         "Finding grounded papers that came before"],
    ["architecture", "Graph drawing",          "Turning the method into a data-flow canvas"],
    ["math",         "Equation ink peel",      "Extracting equations that drive the architecture"],
    ["analysis",     "Story writing",          "Building the plain-English research narrative"],
    ["evidence",     "Evidence pins",          "Attaching source chips to important claims"],
    ["complete",     "Knowledge map reveal",   "Saving the finished peel"],
  ];

  const state = {
    inputType:              "auto",
    selectedPaper:          null,
    activeThreadId:         null,
    currentThread:          null,
    currentPaper:           null,
    currentPeel:            null,
    currentMessages:        [],
    activeTab:              "walkthrough",
    architectureTimer:      null,
    activeArchNodeId:       null,
    mathUnlocked:           false,
    guidedPeelComplete:     false,
    architectureComplete:   false,
    architecturePaused:     false,
    // Set true when renderArchitecture runs; cleared once auto-play fires
    archNeedsAutoPlay:      false,
    activeUploadController: null,
    activeResolveController: null,
    peelingCancelled:       false,
    uploadStatus:           "idle",
    activeArchitectureIndex: 0,
    archRevealOrder:        [],
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /* ─── Screen routing ─── */
  function setScreen(name) {
    $(".app-shell").dataset.screen = name;
  }

  /* ─── Toast ─── */
  function toast(message) {
    const node = $("#toast");
    node.textContent = message;
    node.hidden = false;
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => { node.hidden = true; }, 3800);
  }

  /* ─── Utilities ─── */
  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function compact(value, max = 150) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
  }

  function formatAuthors(authors) {
    if (!authors || !authors.length) return "Authors unavailable";
    if (authors.length <= 3) return authors.join(", ");
    return `${authors.slice(0, 3).join(", ")} and ${authors.length - 3} more`;
  }

  function sectionBody(section) {
    return section && section.body ? section.body : "This section is not available yet.";
  }

  function paragraphHtml(text) {
    return escapeHtml(text)
      .split(/\n{2,}|\n/)
      .filter(Boolean)
      .map(line => `<p>${line}</p>`)
      .join("");
  }

  function evidenceHtml(evidence) {
    const chips = (evidence || []).slice(0, 4);
    if (!chips.length) return '<span class="chip">Evidence pending</span>';
    return chips.map(chip => {
      const label = chip.label || chip.location || chip.source || "Evidence";
      const text  = chip.text ? `: ${compact(chip.text, 68)}` : "";
      return `<span class="chip">${escapeHtml(label + text)}</span>`;
    }).join("");
  }

  function confidenceBadge(section) {
    const confidence = (section && section.confidence) ? section.confidence : "medium";
    return `<span class="confidence-pill confidence-${escapeHtml(confidence)}">${escapeHtml(confidence)} confidence</span>`;
  }

  function setButtonLocked(button, locked, label) {
    if (!button) return;
    button.disabled = Boolean(locked);
    button.classList.toggle("locked", Boolean(locked));
    if (label !== undefined) button.textContent = label;
  }

  /* ─── Upload state display ─── */
  function renderUploadActions(mode) {
    state.uploadStatus = mode || "idle";
    const actions        = $("#uploadActions");
    const cancelBtn      = $("#cancelUploadBtn");
    const chooseAnotherBtn = $("#chooseAnotherPdfBtn");
    if (!actions) return;

    const uploading  = state.uploadStatus === "uploading";
    const hasFile    = state.uploadStatus !== "idle";

    actions.hidden = !hasFile;
    if (cancelBtn)        cancelBtn.hidden = !uploading;
    if (chooseAnotherBtn) chooseAnotherBtn.hidden = false;
  }

  function clearSelectedPaper(message) {
    if (state.activeUploadController) {
      state.activeUploadController.abort();
      state.activeUploadController = null;
    }
    if (state.activeResolveController) {
      state.activeResolveController.abort();
      state.activeResolveController = null;
    }
    state.selectedPaper = null;
    const card = $("#selectedPaperCard");
    if (card) card.hidden = true;
    const candidateStrip = $("#candidateStrip");
    if (candidateStrip) candidateStrip.hidden = true;
    const chip = $("#fileChip");
    if (chip) { chip.hidden = true; chip.textContent = ""; }
    const pdfInput = $("#pdfInput");
    if (pdfInput) pdfInput.value = "";
    renderUploadActions("idle");
    if (message) toast(message);
  }

  /* ─── Tab locks ─── */
  function updateTabLocks() {
    const architectureTab = $('#tabbar button[data-tab="architecture"]');
    const mathTab         = $("#mathTabBtn");
    const chatTab         = $('#tabbar button[data-tab="chat"]');
    const askButton       = $("#askTabBtn");

    if (architectureTab) architectureTab.hidden = !state.guidedPeelComplete;
    if (mathTab)         mathTab.hidden         = !(state.architectureComplete || state.mathUnlocked);
    if (chatTab)         chatTab.hidden         = !state.guidedPeelComplete;
    if (askButton)       askButton.hidden       = !state.guidedPeelComplete;

    setButtonLocked(mathTab, !state.mathUnlocked, state.mathUnlocked ? "Math Peel" : "Math Peel locked");
    setButtonLocked(chatTab, !state.guidedPeelComplete);
    setButtonLocked(askButton, !state.guidedPeelComplete);
  }

  function mapTab(tab) {
    const legacy = { overview: "walkthrough", timeline: "walkthrough", fixes: "walkthrough", results: "walkthrough", verdict: "walkthrough", what: "walkthrough" };
    return legacy[tab] || tab || "walkthrough";
  }

  /* ─── Stage mapping ─── */
  function stageKey(stage, progress) {
    const text = String(stage || "").toLowerCase();
    if (text.includes("cache") || text.includes("save") || progress >= 96) return "complete";
    if (text.includes("validat") || text.includes("evidence"))             return "evidence";
    if (text.includes("analysis") || text.includes("writing"))             return "analysis";
    if (text.includes("math"))                                             return "math";
    if (text.includes("architecture") || text.includes("draw"))            return "architecture";
    if (text.includes("history") || text.includes("related"))             return "history";
    if (text.includes("index"))                                            return "index";
    if (text.includes("extract"))                                          return "extract";
    if (text.includes("resolve") || text.includes("identity"))            return "resolve";
    const idx = Math.max(0, Math.min(STAGES.length - 1, Math.round(((progress || 0) / 100) * (STAGES.length - 1))));
    return STAGES[idx][0];
  }

  function stageByKey(key) {
    return STAGES.find(s => s[0] === key) || STAGES[0];
  }

  /* ─── Topbar ─── */
  function updateTopbar() {
    const title = state.currentPaper ? state.currentPaper.title : "Peel any AI/ML paper";
    $("#topTitle").textContent = title;
    $("#topStatus").textContent = state.currentPeel ? "Peel complete" : "Paper Peeler";

    // Keep chat header in sync
    const chatTitle = $("#chatPaperTitle");
    if (chatTitle) chatTitle.textContent = state.currentPaper ? state.currentPaper.title : "Ask anything about this paper";
  }

  /* ─── Auth ─── */
  async function refreshAuthState() {
    try {
      const sbClient = window.PaperLensAuth || (window.PaperLensAuth = (function(){
        const cfg = window.PAPERLENS_CONFIG || {};
        return (window.supabase && cfg.SUPABASE_URL && cfg.SUPABASE_ANON_KEY)
          ? window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY)
          : null;
      })());

      if (sbClient) {
        const { data: { session } } = await sbClient.auth.getSession();
        if (session?.user) {
          const user = session.user;
          const meta = user.user_metadata || {};
          const name = meta.name || meta.full_name || user.email?.split('@')[0] || 'User';
          const plan = meta.plan || 'free';
          const initial = name.charAt(0).toUpperCase();

          const pill = $("#authPill");
          if (pill) { pill.textContent = user.email; pill.onclick = null; }
          const uname = $("#uname"); if (uname) uname.textContent = name;
          const uplan = $("#uplan"); if (uplan) uplan.textContent = plan === 'pro' ? 'Pro plan' : 'Free plan';
          const uav   = $("#uav");   if (uav)   uav.textContent   = initial;
          return;
        }
      }
    } catch(e) { /* fall through to guest */ }

    // Not signed in
    const pill = $("#authPill");
    if (pill) { pill.textContent = "Sign in"; pill.onclick = () => window.location.href = "login.html"; }
    const uname = $("#uname"); if (uname) uname.textContent = "Guest";
    const uplan = $("#uplan"); if (uplan) uplan.textContent = "Free plan";
    const uav   = $("#uav");   if (uav)   uav.textContent   = "G";
  }

  /* ─── Usage ─── */
  async function refreshUsage() {
    try {
      const usage    = await api.getUsage();
      const peelText = usage.new_peels_limit < 0
        ? `${usage.new_peels_used} peels`
        : `${usage.new_peels_remaining} peels left`;
      const chatText = usage.chat_messages_limit < 0
        ? `${usage.chat_messages_used} chats used`
        : `${usage.chat_messages_remaining} chats left`;
      $("#usagePeels").textContent = peelText;
      $("#usageChats").textContent = chatText;
      return usage;
    } catch (error) {
      $("#usagePeels").textContent = "Sign in";
      $("#usageChats").textContent = "Usage hidden";
      throw error;
    }
  }

  /* ─── Thread list ─── */
  async function refreshThreads() {
    try {
      const data    = await api.listThreads();
      const threads = data.threads || [];
      const list    = $("#threadList");
      const badge   = $("#historyBadge");
      if (badge) badge.textContent = threads.length > 0 ? `${threads.length} paper${threads.length === 1 ? "" : "s"}` : "History";

      if (!threads.length) {
        list.innerHTML = '<div class="empty-state">No peeled papers yet.</div>';
        return;
      }
      list.innerHTML = threads.map(thread => `
        <button class="thread-item ${thread.thread_id === state.activeThreadId ? "active" : ""}" data-thread-id="${escapeHtml(thread.thread_id)}" type="button">
          <svg class="thread-icon" viewBox="0 0 24 24">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <div class="thread-details">
            <strong>${escapeHtml(thread.title || "Untitled paper")}</strong>
            <span>${escapeHtml((thread.paper_id || "").replace(/^arxiv:/, "arXiv "))}</span>
          </div>
        </button>
      `).join("");

      $$(".thread-item", list).forEach(button => {
        button.addEventListener("click", () => {
          loadThread(button.dataset.threadId);
          if (window.innerWidth <= 768) {
            const sb = document.getElementById("sidebar");
            const overlay = document.getElementById("mob-overlay");
            if (sb)      sb.classList.add("closed");
            if (overlay) overlay.classList.remove("show");
          }
        });
      });
    } catch {
      $("#threadList").innerHTML = '<div class="empty-state">Sign in to load history.</div>';
    }
  }

  /* ─── Paper selection ─── */
  function setSelectedPaper(paper, cached) {
    state.selectedPaper          = paper;
    state.activeUploadController = null;
    const card = $("#selectedPaperCard");
    if (card) card.hidden = false;
    $("#selectedMeta").textContent    = cached ? "Already peeled – 0 credits" : `${paper.source_type || "paper"} – ${paper.confidence || "medium"} confidence`;
    $("#selectedTitle").textContent   = paper.title;
    $("#selectedAuthors").textContent = formatAuthors(paper.authors);
    const candidateStrip = $("#candidateStrip");
    if (candidateStrip) candidateStrip.hidden = true;
    renderUploadActions(state.uploadStatus === "uploading" ? "extracted" : state.uploadStatus);
  }

  function renderCandidates(candidates, cached) {
    const grid = $("#candidateGrid");
    grid.innerHTML = candidates.map((paper, index) => `
      <button class="candidate-card" data-index="${index}" type="button">
        <span class="card-kicker">${escapeHtml(paper.source_type || "match")} – ${escapeHtml(paper.confidence || "medium")}</span>
        <strong>${escapeHtml(paper.title)}</strong>
        <p>${escapeHtml(formatAuthors(paper.authors))}</p>
      </button>
    `).join("");
    $("#candidateStrip").hidden = false;
    $$(".candidate-card", grid).forEach(button => {
      button.addEventListener("click", () => {
        $$(".candidate-card", grid).forEach(c => c.classList.remove("active"));
        button.classList.add("active");
        setSelectedPaper(candidates[Number(button.dataset.index)], cached);
      });
    });
  }

  /* ─── Resolve from text ─── */
  async function resolveFromText(event) {
    event.preventDefault();
    const input = $("#paperInput").value.trim();
    if (!input) { toast("Add an arXiv URL, DOI, title, or paper ID first."); return; }

    if (state.activeResolveController) state.activeResolveController.abort();
    state.activeResolveController = new AbortController();

    try {
      $("#selectedPaperCard").hidden = true;
      const result = await api.resolvePaper(input, state.inputType, { signal: state.activeResolveController.signal });
      state.activeResolveController = null;
      if (result.status === "exact" && result.paper) {
        setSelectedPaper(result.paper, result.cached);
        toast(result.cached ? "Already peeled. No credits needed." : "Paper resolved.");
        return;
      }
      if (result.candidates && result.candidates.length) {
        renderCandidates(result.candidates, result.cached);
        return;
      }
      toast(result.message || "No reliable paper match found.");
    } catch (error) {
      state.activeResolveController = null;
      if (error.name === "AbortError") { return; }
      toast(error.message);
    }
  }

  function cancelResolve() {
    if (state.activeResolveController) {
      state.activeResolveController.abort();
      state.activeResolveController = null;
    }
    const cs = $("#candidateStrip");
    if (cs) cs.hidden = true;
    toast("Resolution cancelled.");
  }

  /* ─── PDF upload ─── */
  async function uploadPdf(file) {
    if (!file) return;
    if (file.type !== "application/pdf") { toast("Only PDF files are supported."); return; }
    if (state.activeUploadController) state.activeUploadController.abort();
    state.activeUploadController = new AbortController();
    state.selectedPaper = null;
    const card = $("#selectedPaperCard");
    if (card) card.hidden = true;
    const chip = $("#fileChip");
    chip.hidden = false;
    chip.textContent = `${file.name} – uploading…`;
    renderUploadActions("uploading");
    try {
      const result = await api.uploadPdf(file, { signal: state.activeUploadController.signal });
      state.activeUploadController = null;
      chip.textContent = `${file.name} – extracted`;
      renderUploadActions("extracted");
      setSelectedPaper(result.paper, result.cached);
      toast(result.message || "PDF extracted.");
    } catch (error) {
      state.activeUploadController = null;
      if (error.name === "AbortError") { clearSelectedPaper("Upload cancelled."); return; }
      chip.textContent = `${file.name} – rejected`;
      renderUploadActions("extracted");
      toast(error.message);
    }
  }

  function cancelUpload() {
    if (!state.activeUploadController) { clearSelectedPaper("Selected paper cleared."); return; }
    state.activeUploadController.abort();
  }

  /* ─── Stage rendering ─── */
  function renderStages(activeStage, progress) {
    const key         = stageKey(activeStage, progress);
    const activeIndex = Math.max(0, STAGES.findIndex(s => s[0] === key));
    const [, label, description] = stageByKey(key);
    const screen = $("#peelingScreen");
    if (screen) screen.dataset.stage = key;
    $("#peelingPhase").textContent   = label;
    $("#peelingMessage").textContent = description;
    $("#stageList").innerHTML = STAGES.map(([stageId, stageLabel], index) => {
      const status = index < activeIndex ? "done" : index === activeIndex ? "active" : "";
      return `<div class="stage-item ${status}" data-stage-id="${stageId}">
        <span></span>
        <strong>${escapeHtml(stageLabel)}</strong>
      </div>`;
    }).join("");
    const bar = $("#progressBar");
    const val = Math.max(2, progress || 0);
    bar.style.width = `${val}%`;
    const track = bar.closest(".progress-track");
    if (track) track.setAttribute("aria-valuenow", val);
  }

  /* ─── Peel job ─── */
  async function startPeel() {
    if (!state.selectedPaper) { toast("Resolve or upload a paper first."); return; }

    // Demo mode: intercept AIAYN and load pre-built peel instantly
    const isDemoMode = localStorage.getItem('pl_demo') === 'true';
    const isAIAYN = state.selectedPaper.arxiv_id === '1706.03762' ||
                    state.selectedPaper.canonical_id === 'arxiv:1706.03762';
    if (isDemoMode && isAIAYN) {
      setScreen("peeling");
      $("#peelingTitle").textContent = compact(state.selectedPaper.title, 88);
      renderStages("drawing_architecture", 62);
      setTimeout(async () => {
        try {
          const demoJob = {
            job_id: 'demo-job-aiayn',
            status: 'completed',
            stage: 'served_from_cache',
            progress: 100,
            thread_id: 'demo-thread-aiayn',
            completed_from_cache: true,
            consumed_credit: false
          };
          toast("Demo: Loading pre-built peel — no API call, no credits used.");
          await finishJob(demoJob);
        } catch(e) { setScreen("input"); toast("Demo load failed: " + e.message); }
      }, 1200);
      return;
    }

    setScreen("peeling");
    $("#peelingTitle").textContent = compact(state.selectedPaper.title, 88);
    renderStages("queued", 4);
    state.peelingCancelled = false;
    try {
      const job = await api.createJob(state.selectedPaper);
      if (job.completed_from_cache) {
        toast("Already peeled. Your peel credit was not reduced.");
        await finishJob(job);
        return;
      }
      if (state.peelingCancelled) return;
      await pollJob(job.job_id);
    } catch (error) {
      if (state.peelingCancelled) return;
      setScreen("input");
      toast(error.message);
    }
  }

  async function pollJob(jobId) {
    let attempts = 0;
    while (attempts < 180) {
      if (state.peelingCancelled) {
        throw new Error("Peeling cancelled.");
      }
      attempts += 1;
      const job = await api.getJob(jobId);
      if (state.peelingCancelled) {
        throw new Error("Peeling cancelled.");
      }
      renderStages(job.stage, job.progress);
      if (job.status === "completed") { await finishJob(job); return; }
      if (job.status === "failed")    { throw new Error(job.error_message || "Peel failed. No credit was consumed."); }
      await new Promise(resolve => window.setTimeout(resolve, 1050));
    }
    throw new Error("Peel is still running. Check history in a moment.");
  }

  function cancelPeeling() {
    state.peelingCancelled = true;
    setScreen("input");
    toast("Peeling cancelled.");
  }

  async function finishJob(job) {
    if (!job.thread_id) throw new Error("Peel finished without a thread.");
    await refreshUsage().catch(() => null);
    await loadThread(job.thread_id);
    await refreshThreads();
  }

  /* ─── Load thread ─── */
  function closeSidebarForWorkspace() {
    const sb      = $("#sidebar");
    const overlay = $("#mob-overlay");
    if (sb)      sb.classList.add("closed");
    if (overlay) overlay.classList.remove("show");
  }

  async function loadThread(threadId) {
    let data;
    if (threadId === 'demo-thread-aiayn') {
      data = getDemoThreadData();
    } else {
      data = await api.getThread(threadId);
    }
    state.activeThreadId         = threadId;
    state.currentThread          = data.thread;
    state.currentPaper           = data.paper;
    state.currentPeel            = data.peel;
    state.currentMessages        = data.messages || [];
    state.activeTab              = "walkthrough";
    state.guidedPeelComplete     = false;
    state.architectureComplete   = false;
    state.mathUnlocked           = false;
    state.architecturePaused     = false;
    state.activeArchitectureIndex = 0;
    state.activeArchNodeId       = null;
    state.archRevealOrder        = [];
    updateTopbar();
    renderResult();
    setScreen("result");
    closeSidebarForWorkspace();
    await refreshThreads();
  }

  /* ─── Render result ─── */
  function renderResult() {
    const paper = state.currentPaper;
    const peel  = state.currentPeel;
    if (!paper || !peel) return;

    $("#resultTitle").textContent   = paper.title;
    $("#resultAuthors").textContent = formatAuthors(paper.authors);
    $("#resultMeta").textContent    = peel.completed_from_cache
      ? "Served from cache – 0 credits"
      : `${paper.topic || "General AI"} · ${paper.difficulty || "Intermediate"}`;

    renderWalkthrough(peel);
    renderArchitecture(peel.architecture || {});
    renderMath(peel.math_peel || []);
    renderChat();
    updateTabLocks();
    setTab(mapTab(state.activeTab));

    // v7 — render the new sequential tutor flow on top of legacy renderers
    if (typeof v7_renderTutorFlow === "function") {
      v7_renderTutorFlow(state.currentPaper, state.currentPeel);
    }
  }

  /* ─── Story / Paper Walkthrough ─── */
  function walkthroughSectionHtml(index, key, fallbackTitle, section) {
    return `
      <article class="walkthrough-section peel-chapter" id="walkthrough-${key}" data-peel-step="${index}">
        <div class="walkthrough-index">${String(index).padStart(2, "0")}</div>
        <div class="walkthrough-card peel-copy">
          <div class="walkthrough-card-head">
            <span>${escapeHtml(fallbackTitle)}</span>
            ${confidenceBadge(section)}
          </div>
          <h3>${escapeHtml(section && section.title ? section.title : fallbackTitle)}</h3>
          <div class="walkthrough-body">${paragraphHtml(sectionBody(section))}</div>
          <div class="evidence-row">${evidenceHtml(section && section.evidence)}</div>
        </div>
      </article>
    `;
  }

  function lineageHtml(peel) {
    const related = (peel.related_papers || []).slice(0, 3);
    if (!related.length) {
      return `
        <div class="lineage-empty">
          <span>No verified lineage yet</span>
          <p>${escapeHtml(sectionBody(peel.sections && peel.sections.timeline))}</p>
        </div>
      `;
    }
    return `
      <div class="lineage-path">
        ${related.map((paper, index) => `
          <article class="lineage-node">
            <span>${escapeHtml(paper.year || `Step ${index + 1}`)}</span>
            <strong>${escapeHtml(compact(paper.title, 92))}</strong>
            <dl>
              <div>
                <dt>Tried</dt>
                <dd>${escapeHtml(paper.what_it_tried || "Earlier work in this lineage.")}</dd>
              </div>
              <div>
                <dt>Limit</dt>
                <dd>${escapeHtml(paper.limitation || "Specific limitation was not extracted from the available sources.")}</dd>
              </div>
              <div>
                <dt>Connects</dt>
                <dd>${escapeHtml(paper.connection_to_this_paper || "Connected to the current paper by the research graph.")}</dd>
              </div>
            </dl>
          </article>
        `).join("")}
      </div>
    `;
  }

  function renderWalkthrough(peel) {
    const sections    = peel.sections || {};
    const walkthroughItems  = [
      ["what",      "Simple explanation",      sections.what],
      ["timeline",  "Historical lineage",      sections.timeline],
      ["fixes",     "What is new",             sections.fixes],
      ["results",   "Results and benchmarks",  sections.results],
      ["verdict",   "Should you care",         sections.verdict],
    ];

    $("#tab-walkthrough").innerHTML = `
      <div class="walkthrough-workspace">
        <aside class="walkthrough-rail" aria-label="Peel Map navigation">
          <span>Peel Map</span>
          ${walkthroughItems.map(([key, label], index) => `
            <button type="button" data-walkthrough-target="walkthrough-${key}">
              <strong>${String(index + 1).padStart(2, "0")}</strong>
              ${escapeHtml(label)}
            </button>
          `).join("")}
          <button type="button" data-open-tab="architecture" class="walkthrough-rail-action" hidden>
            <strong>06</strong>
            Open architecture
          </button>
        </aside>
        <div class="walkthrough-flow" id="walkthroughFlow">
          <div class="walkthrough-opening">
            <span>${escapeHtml(state.currentPaper && state.currentPaper.topic || "Research paper")}</span>
            <h3>${escapeHtml(state.currentPaper && state.currentPaper.title || "Peeled paper")}</h3>
            <p>PaperLens walks through the paper like a tutor: first the core idea, then the lineage, then the gap, evidence, verdict, and the next deep dive.</p>
          </div>

          ${walkthroughSectionHtml(1, "what", "Simple explanation", sections.what)}

          <p class="walkthrough-transition" aria-hidden="true">Paper peeled. Now let's deep dive into its history.</p>

          <article class="walkthrough-section story-lineage peel-chapter" id="walkthrough-timeline" data-peel-step="2">
            <div class="walkthrough-index">02</div>
            <div class="walkthrough-card peel-copy">
              <div class="walkthrough-card-head">
                <span>Historical lineage</span>
                ${confidenceBadge(sections.timeline)}
              </div>
              <h3>${escapeHtml(sections.timeline && sections.timeline.title || "What came before?")}</h3>
              <div class="walkthrough-body">${paragraphHtml(sectionBody(sections.timeline))}</div>
              ${lineageHtml(peel)}
              <div class="evidence-row">${evidenceHtml(sections.timeline && sections.timeline.evidence)}</div>
            </div>
          </article>

          ${walkthroughSectionHtml(3, "fixes",   "What is new",            sections.fixes)}
          ${walkthroughSectionHtml(4, "results", "Results and benchmarks",  sections.results)}
          ${walkthroughSectionHtml(5, "verdict", "Should you care",         sections.verdict)}

          <article class="story-bridge guided-complete-cta" id="guidedCompleteCta">
            <div>
              <span>Guided peel complete</span>
              <strong>Now let's open the architecture.</strong>
            </div>
            <button class="primary-btn btn-glow" type="button" data-open-tab="architecture">
              Open Architecture Canvas
            </button>
          </article>
        </div>
      </div>
    `;

    $$("[data-walkthrough-target]", $("#tab-walkthrough")).forEach(button => {
      button.addEventListener("click", () => {
        const target = $(`#${button.dataset.walkthroughTarget}`);
        if (target) {
          target.classList.add("revealed");
          target.scrollIntoView({ behavior: "smooth", block: "start" });
          if (button.dataset.walkthroughTarget === "walkthrough-verdict") markGuidedPeelComplete();
        }
      });
    });

    $$("[data-open-tab]", $("#tab-walkthrough")).forEach(button => {
      button.addEventListener("click", () => setTab(button.dataset.openTab));
    });

    setupGuidedReveal();
  }

  function setupGuidedReveal() {
    const chapters = $$(".peel-chapter", $("#tab-walkthrough"));
    if (!chapters.length) return;

    // Reveal first chapter immediately
    chapters[0].classList.add("revealed");

    if (!("IntersectionObserver" in window)) {
      chapters.forEach(c => c.classList.add("revealed"));
      markGuidedPeelComplete();
      return;
    }

    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("revealed");
        const step = Number(entry.target.dataset.peelStep || 0);

        // Sync rail button active state
        $$("[data-walkthrough-target]", $("#tab-walkthrough")).forEach(btn => {
          btn.classList.toggle("active", btn.dataset.walkthroughTarget === entry.target.id);
        });

        if (step >= 5) markGuidedPeelComplete();
      });
    }, { root: $("#walkthroughFlow"), threshold: 0.3 });

    chapters.forEach(c => observer.observe(c));
  }

  function markGuidedPeelComplete() {
    if (state.guidedPeelComplete) return;
    state.guidedPeelComplete = true;
    const cta = $("#guidedCompleteCta");
    if (cta) cta.classList.add("revealed", "is-unlocked");
    $$("[data-open-tab='architecture']", $("#tab-walkthrough")).forEach(btn => { btn.hidden = false; });
    updateTabLocks();
  }

  /* ─── Architecture ─── */
  function renderArchitecture(graph) {
    const nodes = (graph.nodes && graph.nodes.length)
      ? graph.nodes
      : [{ id: "method", label: "Core method", type: "module" }];
    const edges       = graph.edges || [];
    const revealOrder = (graph.reveal_order && graph.reveal_order.length)
      ? graph.reveal_order
      : nodes.map(n => n.id);

    state.archRevealOrder = revealOrder;

    // Compute layout — all coordinates live inside the viewBox
    const positions = layoutNodes(nodes);
    // ViewBox dimensions derived from the layout (see layoutNodes)
    const cols   = Math.min(4, Math.max(2, nodes.length));
    const rows   = Math.ceil(nodes.length / cols);
    // Node card: 176w × 84h; padding 36 each side; row gap 96
    const vbW    = 36 + cols * 176 + (cols - 1) * 48 + 36;  // total width
    const vbH    = Math.max(360, 36 + rows * 84 + (rows - 1) * 96 + 36); // total height

    const svg = $("#architectureCanvas");
    svg.innerHTML = `
      <title>Paper architecture graph</title>
      <defs>
        <linearGradient id="archNodeFill" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%"   stop-color="rgba(168,196,240,0.14)"/>
          <stop offset="100%" stop-color="rgba(245,230,204,0.07)"/>
        </linearGradient>
        <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="rgba(245,230,204,0.72)"/>
        </marker>
      </defs>
      <g class="arch-grid-lines">
        ${Array.from({ length: Math.ceil(vbH / 48) }, (_, i) => `<path d="M0 ${i * 48} H${vbW}"/>`).join("")}
      </g>
      ${edges.map(edge => {
        const from = positions[edge.from];
        const to   = positions[edge.to];
        if (!from || !to) return "";
        // Bezier from right-center of source to left-center of dest
        const x1 = from.x + 176, y1 = from.y + 42;
        const x2 = to.x,         y2 = to.y + 42;
        const cx  = (x1 + x2) / 2;
        return `<g class="arch-edge-group" data-edge-from="${escapeHtml(edge.from)}" data-edge-to="${escapeHtml(edge.to)}">
          <path class="arch-edge" marker-end="url(#arrow)" d="M${x1} ${y1} C${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}"/>
        </g>`;
      }).join("")}
      ${nodes.map(node => {
        const pos = positions[node.id] || { x: 36, y: 36 };
        return `<g class="arch-node" data-node-id="${escapeHtml(node.id)}" transform="translate(${pos.x},${pos.y})">
          <rect class="node-border" width="176" height="84" rx="14"/>
          <rect class="node-inner" x="6" y="6" width="164" height="72" rx="10" fill="none" stroke="rgba(255,255,255,0.03)" stroke-dasharray="4 4"/>
          <g class="sub-nodes-group">
            <circle cx="36" cy="56" r="3.5" class="sub-node-dot"/>
            <circle cx="88" cy="56" r="3.5" class="sub-node-dot"/>
            <circle cx="140" cy="56" r="3.5" class="sub-node-dot"/>
            <line x1="39.5" y1="56" x2="84.5" y2="56" class="sub-node-link"/>
            <line x1="91.5" y1="56" x2="136.5" y2="56" class="sub-node-link"/>
          </g>
          <circle class="port port-in" cx="0" cy="42" r="3.5"/>
          <circle class="port port-out" cx="176" cy="42" r="3.5"/>
          <circle cx="22" cy="22" r="5" class="node-bullet"/>
          <text class="node-title" x="34" y="26">${escapeHtml(compact(node.label || node.id, 22))}</text>
          <text class="node-subtitle" x="16" y="56" fill="rgba(246,247,249,0.48)" font-size="11">${escapeHtml(compact(node.type || "module", 26))}</text>
        </g>`;
      }).join("")}
    `;
    // Responsive: viewBox scales to container, preserveAspectRatio keeps aspect
    svg.setAttribute("viewBox", `0 0 ${vbW} ${vbH}`);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

    $("#flowSteps").innerHTML = (graph.data_flow_steps || []).map((step, i) =>
      `<li data-flow-step="${i}"><span>${String(i + 1).padStart(2, "0")}</span>${escapeHtml(step)}</li>`
    ).join("");

    $$(".arch-node", svg).forEach(node => {
      node.addEventListener("click", () => {
        state.activeArchNodeId = node.dataset.nodeId;
        updateArchInspector(graph, state.activeArchNodeId);
        $$(".arch-node", svg).forEach(n => n.classList.toggle("selected", n.dataset.nodeId === state.activeArchNodeId));
      });
    });

    state.activeArchNodeId        = revealOrder[0] || nodes[0].id;
    state.activeArchitectureIndex = 0;
    state.architectureComplete    = false;
    state.architecturePaused      = false;
    state.mathUnlocked            = false;
    // Mark that the first tab-open should trigger auto-play
    state.archNeedsAutoPlay       = true;
    updateArchInspector(graph, state.activeArchNodeId);
    // Show first node immediately (no animation yet — will fire on tab open)
    revealArchitecture(revealOrder, 0, false);
    updateArchitectureControls(revealOrder);
    updatePauseBtn();
  }

  function layoutNodes(nodes) {
    const positions = {};
    const count   = Math.max(nodes.length, 1);
    const columns = Math.min(4, Math.max(2, count));
    // Node card width: 176px. Gap between cards: 48px. Left margin: 36px.
    const colStep = 176 + 48;   // 224px per column
    const rowStep = 84 + 96;    // 180px per row (node height 84 + gap 96)
    nodes.forEach((node, index) => {
      const col = index % columns;
      const row = Math.floor(index / columns);
      positions[node.id] = { x: 36 + col * colStep, y: 36 + row * rowStep };
    });
    return positions;
  }

  let activeTypeTimer = null;
  function streamTypeInspector(text) {
    const bodyNode = $("#archNodeBody");
    if (!bodyNode) return;
    window.clearTimeout(activeTypeTimer);
    bodyNode.textContent = "";
    bodyNode.classList.add("tutor-typing");
    let index = 0;
    
    function typeNextChar() {
      if (index < text.length) {
        bodyNode.textContent += text[index];
        index++;
        activeTypeTimer = window.setTimeout(typeNextChar, 8 + Math.random() * 6);
      } else {
        bodyNode.classList.remove("tutor-typing");
      }
    }
    typeNextChar();
  }

  function updateArchInspector(graph, nodeId) {
    const node     = (graph.nodes || []).find(n => n.id === nodeId) || {};
    const fallback = "PaperLens identified this as one layer in the method. The full explanation grows stronger when the model extracts richer architecture evidence from the paper.";
    const title    = $("#archNodeTitle");
    const body     = $("#archNodeBody");
    if (title) title.textContent = node.label || "Selected layer";
    if (body) {
      const text = (graph.node_explanations && graph.node_explanations[nodeId]) || fallback;
      streamTypeInspector(text);
    }
  }

  function peelNextBlockOneByOne(revealOrder, blockIndex) {
    if (state.architecturePaused) {
      state.architectureTimer = window.setTimeout(() => {
        peelNextBlockOneByOne(revealOrder, blockIndex);
      }, 1000);
      return;
    }
    if (blockIndex >= revealOrder.length) {
      state.architectureComplete = true;
      const status = $("#architectureStatus");
      if (status) status.textContent = "Now let's do some calculations.";
      state.mathUnlocked = true;
      renderMath(state.currentPeel ? state.currentPeel.math_peel || [] : []);
      updateTabLocks();
      updateArchitectureControls(revealOrder);
      return;
    }
    
    const nodeId = revealOrder[blockIndex];
    state.activeArchitectureIndex = blockIndex;
    state.activeArchNodeId = nodeId;
    
    $$(".arch-node").forEach(node => {
      if (node.dataset.nodeId === nodeId) {
        node.classList.add("peeled", "revealed");
        node.classList.add("selected");
      } else {
        node.classList.remove("selected");
      }
    });
    
    const status = $("#architectureStatus");
    if (status) {
      const node = (state.currentPeel && state.currentPeel.architecture && state.currentPeel.architecture.nodes || []).find(n => n.id === nodeId) || {};
      status.textContent = `Let's now completely peel this: opening ${node.label || nodeId}...`;
    }
    
    const graph = state.currentPeel ? state.currentPeel.architecture || {} : {};
    updateArchInspector(graph, nodeId);
    
    state.architectureTimer = window.setTimeout(() => {
      peelNextBlockOneByOne(revealOrder, blockIndex + 1);
    }, 3200);
  }

  function revealArchitecture(revealOrder, upto, animate) {
    window.clearTimeout(state.architectureTimer);
    state.activeArchitectureIndex = Math.max(0, Math.min(upto, revealOrder.length - 1));
    const visible = new Set(revealOrder.slice(0, upto + 1));

    $$(".arch-node").forEach(node => {
      node.classList.toggle("revealed", visible.has(node.dataset.nodeId));
      node.classList.toggle("selected", node.dataset.nodeId === revealOrder[upto]);
      if (!visible.has(node.dataset.nodeId)) {
        node.classList.remove("peeled");
      }
    });
    $$(".arch-edge-group").forEach(edge => {
      edge.classList.toggle("revealed", visible.has(edge.dataset.edgeFrom) && visible.has(edge.dataset.edgeTo));
    });
    $$("#flowSteps li").forEach((step, i) => {
      step.classList.toggle("active", i <= upto);
    });

    const graph = state.currentPeel ? state.currentPeel.architecture || {} : {};
    if (revealOrder[upto]) {
      state.activeArchNodeId = revealOrder[upto];
      updateArchInspector(graph, revealOrder[upto]);
    }

    if (animate && upto < revealOrder.length - 1 && !state.architecturePaused) {
      state.architectureTimer = window.setTimeout(() => {
        revealArchitecture(revealOrder, upto + 1, true);
      }, 1050);
    }

    if (upto >= revealOrder.length - 1) {
      const status = $("#architectureStatus");
      if (status) status.textContent = "Let's now completely peel this.";
      
      if (animate && !state.architecturePaused) {
        window.clearTimeout(state.architectureTimer);
        state.architectureTimer = window.setTimeout(() => {
          peelNextBlockOneByOne(revealOrder, 0);
        }, 1400);
      } else if (!animate) {
        state.architectureComplete = true;
        updateTabLocks();
        updateArchitectureControls(revealOrder);
      }
    } else {
      const status = $("#architectureStatus");
      if (status) status.textContent = `Layer ${Math.min(state.activeArchitectureIndex + 1, revealOrder.length)} of ${revealOrder.length}: drawing the architecture.`;
    }
    updateArchitectureControls(revealOrder);
    updatePauseBtn();
  }

  function playArchitecture() {
    const graph       = state.currentPeel ? state.currentPeel.architecture || {} : {};
    const nodes       = (graph.nodes && graph.nodes.length) ? graph.nodes : [{ id: "method" }];
    const revealOrder = (graph.reveal_order && graph.reveal_order.length) ? graph.reveal_order : nodes.map(n => n.id);
    state.archRevealOrder     = revealOrder;
    state.architectureComplete = false;
    state.architecturePaused  = false;
    state.mathUnlocked        = false;
    renderMath(state.currentPeel ? state.currentPeel.math_peel || [] : []);
    updateTabLocks();
    revealArchitecture(revealOrder, 0, true);
  }

  function nextArchitectureLayer() {
    const graph       = state.currentPeel ? state.currentPeel.architecture || {} : {};
    const nodes       = (graph.nodes && graph.nodes.length) ? graph.nodes : [{ id: "method" }];
    const revealOrder = (graph.reveal_order && graph.reveal_order.length) ? graph.reveal_order : nodes.map(n => n.id);
    revealArchitecture(revealOrder, state.activeArchitectureIndex + 1, false);
  }

  function togglePauseArchitecture() {
    state.architecturePaused = !state.architecturePaused;
    if (!state.architecturePaused && !state.architectureComplete) {
      // Resume
      const graph       = state.currentPeel ? state.currentPeel.architecture || {} : {};
      const nodes       = (graph.nodes && graph.nodes.length) ? graph.nodes : [{ id: "method" }];
      const revealOrder = (graph.reveal_order && graph.reveal_order.length) ? graph.reveal_order : nodes.map(n => n.id);
      revealArchitecture(revealOrder, state.activeArchitectureIndex + 1, true);
    } else {
      window.clearTimeout(state.architectureTimer);
    }
    updatePauseBtn();
  }

  function updatePauseBtn() {
    const btn = $("#pauseArchitectureBtn");
    if (!btn) return;
    const paused = state.architecturePaused;
    btn.dataset.paused = paused ? "true" : "false";
    btn.innerHTML = paused
      ? `<svg viewBox="0 0 24 24" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg> Resume`
      : `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg> Pause`;
    btn.disabled = state.architectureComplete;
    btn.classList.toggle("locked", state.architectureComplete);
  }

  function updateArchitectureControls(revealOrder) {
    const complete  = state.architectureComplete;
    const nextBtn   = $("#nextArchitectureBtn");
    const mathBtn   = $("#peelMathFromArchBtn");
    if (nextBtn) {
      nextBtn.disabled = complete;
      nextBtn.classList.toggle("locked", complete);
    }
    if (mathBtn) {
      mathBtn.disabled = !complete;
      mathBtn.classList.toggle("locked", !complete);
      mathBtn.hidden   = !complete;
    }
  }

  /* ─── Math Peel ─── */
  function renderMath(equations) {
    const mathTab = $("#mathTabBtn");
    if (mathTab) {
      mathTab.classList.toggle("locked", !state.mathUnlocked);
      mathTab.textContent = state.mathUnlocked ? "Math Peel" : "Math Peel locked";
    }

    if (!state.mathUnlocked) {
      $("#tab-math").innerHTML = `
        <div class="math-locked">
          <div class="math-lock-mark" aria-hidden="true"><span></span><span></span><span></span></div>
          <span>Math Peel</span>
          <h3>Peel the architecture first, then open the equations that make it work.</h3>
          <p>V1 Math Peel stays separate so the paper story does not feel crowded. It focuses only on important method equations and explains why each one changes model behavior.</p>
          <button class="primary-btn btn-glow" type="button" id="unlockMathBtn">Peel the math</button>
        </div>
      `;
      const unlock = $("#unlockMathBtn");
      if (unlock) unlock.addEventListener("click", unlockMath);
      return;
    }

    if (!equations.length) {
      $("#tab-math").innerHTML = `
        <div class="math-empty-state">
          <span>Math Peel</span>
          <h3>No key method equations were extracted for this paper.</h3>
          <p>PaperLens will keep the workspace honest: the current peel did not find an equation strong enough to explain as architecture-driving math.</p>
        </div>
      `;
      return;
    }

    const topEquations = equations.slice(0, 5);
    $("#tab-math").innerHTML = `
      <div class="math-workspace">
        <div class="math-intro">
          <span>Equation ink peel</span>
          <h3>Now let's do some calculations.</h3>
          <p>Only the important method equations are shown in V1, with the symbols and behavior impact explained beside the architecture.</p>
        </div>
        <div class="math-list">
          ${topEquations.map((eq, i) => `
            <article class="math-card ${i === 0 ? "active-equation" : ""}">
              <span class="card-kicker">Equation ${i + 1}${eq.location ? ` · ${escapeHtml(eq.location)}` : ""}</span>
              <div class="equation-box">${typeof katex !== 'undefined' ? katex.renderToString(eq.latex, {throwOnError: false, displayMode: true}) : escapeHtml(eq.latex)}</div>
              <div class="symbol-grid">
                ${(eq.symbols || []).map(s => `<span>${escapeHtml(s.symbol)}: ${escapeHtml(s.meaning)}</span>`).join("")}
              </div>
              <div class="math-meta">
                <div><strong>Plain meaning</strong><p>${escapeHtml(eq.plain_meaning || "Not extracted.")}</p></div>
                <div><strong>Role in architecture</strong><p>${escapeHtml(eq.role_in_architecture || "Not extracted.")}</p></div>
                <div><strong>Behavior if changed</strong><p>${escapeHtml(eq.behavior_if_changed || "Not extracted.")}</p></div>
                <div><strong>Evidence</strong><p>${escapeHtml(compact((eq.evidence || []).map(e => e.text || e.label).join(" "), 220) || "Evidence pending")}</p></div>
              </div>
            </article>
          `).join("")}
        </div>
      </div>
    `;
  }

  function unlockMath() {
    if (!state.architectureComplete) {
      toast("Finish the architecture playback first.");
      setTab("architecture");
      return;
    }
    state.mathUnlocked = true;
    renderMath(state.currentPeel ? state.currentPeel.math_peel || [] : []);
    updateTabLocks();
    setTab("math");
    toast("Math Peel unlocked from the architecture.");
  }

  /* ─── Chat ─── */
  function renderChat() {
    const questions = state.currentPeel && state.currentPeel.suggested_questions
      ? state.currentPeel.suggested_questions
      : [];

    const grid = $("#suggestionGrid");
    if (grid) {
      grid.innerHTML = questions.map(q => `
        <button type="button" data-question="${escapeHtml(q)}">${escapeHtml(q)}</button>
      `).join("");
      $$("#suggestionGrid button").forEach(btn => {
        btn.addEventListener("click", () => {
          const input = $("#chatInput");
          if (input) { input.value = btn.dataset.question; input.focus(); }
        });
      });
    }

    const log = $("#chatLog");
    if (log) {
      log.innerHTML = (state.currentMessages || []).map(m => chatBubbleHtml(m.role, m.content)).join("");
      log.scrollTop = log.scrollHeight;
    }

    // Update chat header title
    const chatTitle = $("#chatPaperTitle");
    if (chatTitle && state.currentPaper) chatTitle.textContent = state.currentPaper.title;
  }

  const CHAT_LOGO_SVG = `<svg width="16" height="16" viewBox="0 0 28 28" fill="none" aria-hidden="true">
    <circle cx="13" cy="13" r="9" stroke="url(#pl-cg)" stroke-width="1.8"/>
    <circle cx="13" cy="13" r="4.5" stroke="url(#pl-cg)" stroke-width="1" opacity="0.6"/>
    <circle cx="13" cy="13" r="1.8" fill="url(#pl-cg)"/>
    <line x1="19.5" y1="19.5" x2="25.5" y2="25.5" stroke="white" stroke-width="2" stroke-linecap="round" opacity="0.8"/>
    <defs><linearGradient id="pl-cg" x1="0" y1="0" x2="28" y2="28">
      <stop offset="0%" stop-color="#a8c4f0"/><stop offset="100%" stop-color="#f5e6cc"/>
    </linearGradient></defs>
  </svg>`;

  function chatBubbleHtml(role, content) {
    // v7 bare style — used inside the new chat-bare pane
    if (role === "user") {
      return `<div class="chat-msg-user">${escapeHtml(content)}</div>`;
    }
    const paragraphs = String(content || "").split(/\n\s*\n/).map(p => `<p>${escapeHtml(p)}</p>`).join("");
    return `<div class="chat-msg-assistant"><div class="chat-msg-assistant-avatar logo-avatar">${CHAT_LOGO_SVG}</div><div class="chat-msg-assistant-body">${paragraphs}</div></div>`;
  }

  async function sendChat(event) {
    event.preventDefault();
    const input    = $("#chatInput");
    if (!input) return;
    const question = input.value.trim();
    if (!question || !state.activeThreadId) {
      if (!state.activeThreadId) toast("Open a paper first to start chatting.");
      return;
    }

    const log = $("#chatLog");
    if (!log) return;
    log.insertAdjacentHTML("beforeend", chatBubbleHtml("user", question));

    // v7 thinking bubble — three pulsing orbs
    const assistant = document.createElement("div");
    assistant.className = "chat-msg-assistant";
    assistant.innerHTML = `
      <div class="chat-msg-assistant-avatar logo-avatar">${CHAT_LOGO_SVG}</div>
      <div class="chat-msg-assistant-body"><div class="chat-thinking" aria-label="Thinking"><span></span><span></span><span></span></div></div>
    `;
    log.appendChild(assistant);
    input.value = "";
    log.scrollTop = log.scrollHeight;

    const bodyEl = assistant.querySelector(".chat-msg-assistant-body");
    try {
      await api.streamChat(state.activeThreadId, question, (_, fullText) => {
        if (!bodyEl) return;
        const safe = String(fullText || "").split(/\n\s*\n/).map(p => `<p>${escapeHtml(p)}</p>`).join("");
        bodyEl.innerHTML = safe || '<div class="chat-thinking"><span></span><span></span><span></span></div>';
        log.scrollTop = log.scrollHeight;
      });
      const finalText = bodyEl ? bodyEl.textContent.trim() : "";
      state.currentMessages.push({ role: "user",      content: question });
      state.currentMessages.push({ role: "assistant", content: finalText });
      await refreshUsage().catch(() => null);
    } catch (error) {
      if (bodyEl) bodyEl.textContent = (error && error.message) || "Chat error";
    }
  }

  /* ─── Tab routing ─── */
  function setTab(tab) {
    const nextTab = mapTab(tab);

    if ((nextTab === "architecture" || nextTab === "chat" || nextTab === "math") && !state.guidedPeelComplete) {
      toast("Finish the Paper Walkthrough first. Architecture and chat unlock at the end.");
      return;
    }
    if (nextTab === "math" && !state.mathUnlocked) {
      state.activeTab = "architecture";
      $$("#tabbar button").forEach(btn => btn.classList.toggle("active", btn.dataset.tab === "architecture"));
      $$(".tab-panel").forEach(panel => panel.classList.toggle("active", panel.id === "tab-architecture"));
      toast("Open Architecture Canvas first, then click Peel the math.");
      return;
    }

    state.activeTab = nextTab;
    updateTabLocks();

    $$("#tabbar button").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.tab === nextTab);
      btn.setAttribute("aria-selected", btn.dataset.tab === nextTab ? "true" : "false");
    });
    $$(".tab-panel").forEach(panel => {
      panel.classList.toggle("active", panel.id === `tab-${nextTab}`);
    });

    // Auto-start architecture drawing the first time the tab is opened
    if (nextTab === "architecture" && state.archNeedsAutoPlay) {
      state.archNeedsAutoPlay = false;
      // Small defer so the panel is visible before animation starts
      window.setTimeout(playArchitecture, 120);
    }
  }

  /* ─── Reset ─── */
  function resetForNewPeel() {
    clearSelectedPaper();
    state.currentThread          = null;
    state.currentPaper           = null;
    state.currentPeel            = null;
    state.currentMessages        = [];
    state.activeTab              = "walkthrough";
    state.guidedPeelComplete     = false;
    state.architectureComplete   = false;
    state.archNeedsAutoPlay      = false;
    state.mathUnlocked           = false;
    state.architecturePaused     = false;
    state.activeArchNodeId       = null;
    state.activeArchitectureIndex = 0;
    state.archRevealOrder        = [];
    const pi = $("#paperInput");
    if (pi) pi.value = "";
    const cs = $("#candidateStrip");
    if (cs) cs.hidden = true;
    const sc = $("#selectedPaperCard");
    if (sc) sc.hidden = true;
    const fc = $("#fileChip");
    if (fc) fc.hidden = true;
    updateTabLocks();
    setScreen("input");
    updateTopbar();
  }

  /* ─── Event bindings ─── */
  function bindEvents() {
    if (window.innerWidth <= 768) {
      const sidebar = $("#sidebar");
      if (sidebar) sidebar.classList.add("closed");
    }

    $("#peelForm").addEventListener("submit", resolveFromText);
    $("#startPeelBtn").addEventListener("click", startPeel);
    $("#newPeelBtn").addEventListener("click", resetForNewPeel);
    $("#refreshUsageBtn").addEventListener("click", () =>
      refreshUsage().then(() => toast("Usage refreshed.")).catch(e => toast(e.message))
    );
    $("#choosePdfBtn").addEventListener("click", () => $("#pdfInput").click());
    $("#chooseAnotherPdfBtn").addEventListener("click", () => $("#pdfInput").click());
    $("#cancelUploadBtn").addEventListener("click", cancelUpload);
    $("#cancelResolveBtn").addEventListener("click", cancelResolve);
    $("#cancelPeelBtn").addEventListener("click", cancelPeeling);
    $("#clearSelectedBtn").addEventListener("click", () => clearSelectedPaper("Selected paper cleared."));
    $("#pdfInput").addEventListener("change", e => uploadPdf(e.target.files[0]));
    $("#chatForm").addEventListener("submit", sendChat);
    // Legacy architecture/math/replay buttons were removed when v7 took over.
    // Guarded so a missing element can never crash init() (which would prevent
    // history from loading).
    const _bind = (id, fn, ev = "click") => {
      const el = document.getElementById(id);
      if (el) el.addEventListener(ev, fn);
    };
    _bind("playArchitectureBtn",  playArchitecture);
    _bind("pauseArchitectureBtn", togglePauseArchitecture);
    _bind("nextArchitectureBtn",  nextArchitectureLayer);
    _bind("peelMathFromArchBtn",  unlockMath);
    _bind("replayPeelBtn", () => {
      setScreen("peeling");
      renderStages("served_from_cache", 100);
      window.setTimeout(() => setScreen("result"), 1500);
    });
    _bind("askTabBtn", () => v7_revealStage("chat"));

    $$(".seg").forEach(button => {
      button.addEventListener("click", () => {
        $$(".seg").forEach(b => b.classList.remove("active"));
        button.classList.add("active");
        state.inputType = button.dataset.inputType;
      });
    });

    $$("#tabbar button").forEach(button => {
      button.addEventListener("click", () => setTab(button.dataset.tab));
    });

    // Drop zone
    const dropZone = $("#dropZone");
    if (dropZone) {
      ["dragenter", "dragover"].forEach(ev => {
        dropZone.addEventListener(ev, e => { e.preventDefault(); dropZone.classList.add("dragging"); });
      });
      ["dragleave", "drop"].forEach(ev => {
        dropZone.addEventListener(ev, e => { e.preventDefault(); dropZone.classList.remove("dragging"); });
      });
      dropZone.addEventListener("drop", e => uploadPdf(e.dataTransfer.files[0]));
    }
  }

  /* ─── Init ─── */
  async function init() {
    bindEvents();
    renderStages("queued", 0);
    updateTabLocks();
    renderUploadActions("idle");
    // Each init step is isolated — a failure or stall in one must NOT block the rest.
    // Run auth + usage + threads in parallel; even if any rejects, history still loads.
    await Promise.allSettled([
      refreshAuthState(),
      refreshUsage(),
      refreshThreads(),
    ]);

    const params   = new URLSearchParams(window.location.search);
    const threadId = params.get("thread");
    if (threadId) await loadThread(threadId).catch(e => toast(e.message));

    const tab = params.get("tab");
    if (tab) setTab(tab);

    updateTopbar();
  }

  /* ═══════════════════════════════════════════════
     v7 — Sequential Tutor Flow (PaperLens redesign)
     ═══════════════════════════════════════════════ */

  // Internal state for the v7 stage flow
  const v7 = {
    stagesUnlocked: { walkthrough: true, architecture: false, math: false, chat: false },
    chapterObserver: null,
    archExpanded: false,
    archGraph: null,
    archFocusIndex: 0,
    archNodeOrder:   [],      // BFS-ordered node IDs for Prev/Next stepping
    archStepIndex:   0,       // current step position in archNodeOrder
    archAutoTimer:   null,    // setTimeout handle for auto-play
    archAutoPlaying: false,   // is auto-play currently running?
    streamObserver: null,
    seqObserver: null,
  };

  /* ── Orchestrator ── */
  function v7_renderTutorFlow(paper, peel) {
    if (!paper || !peel) return;

    // Reset stage visibility on every render (replay support)
    v7.stagesUnlocked = { walkthrough: true, architecture: false, math: false, chat: false };
    v7.archExpanded = false;
    v7.archGraph = peel.architecture || { nodes: [], edges: [] };

    ["stageArchitecture", "stageMath", "stageChat"].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.hidden = true;
        el.classList.remove("is-active", "is-emerging");
      }
    });
    // Also clear the active walkthrough state so v7_showStage replays its emerge
    const walkEl = document.getElementById("stageWalkthrough");
    if (walkEl) walkEl.classList.remove("is-active", "is-emerging");
    // Reset CTA reveal state (both beats) so the promise+button animate again
    ["ctaToArch", "ctaToMath", "ctaToChat"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove("is-ready", "is-buttoned");
    });
    // Disconnect any leftover IntersectionObserver from the previous paper
    if (v7.chapterObserver)  { v7.chapterObserver.disconnect();  v7.chapterObserver  = null; }
    if (v7.streamObserver)   { v7.streamObserver.disconnect();   v7.streamObserver   = null; }
    if (v7.seqObserver)      { v7.seqObserver.disconnect();      v7.seqObserver      = null; }
    if (v7.flowStepObserver) { v7.flowStepObserver.disconnect(); v7.flowStepObserver = null; }

    v7_renderWalkthroughChapters(peel);
    v7_setupChapterReveal();
    v7_setupStageCTAs();

    // Pre-render the static text for stage 2/3 inspector panels
    const archInspectorTitle = $("#archNodeTitle");
    const archInspectorBody  = $("#archNodeBody");
    if (archInspectorTitle) archInspectorTitle.textContent = "Watch it draw itself";
    if (archInspectorBody)  archInspectorBody.textContent  = "Each block animates in as PaperLens follows the paper's data flow.";

    // Render suggested questions + existing thread messages into chat stage
    v7_renderChatBare(paper, peel);

    // Deck model: open on the Walkthrough window, expose the section nav
    v7_bindPillNav();
    v7_updatePillNav();
    v7_showStage("walkthrough");
  }

  /* ── Walkthrough chapters with streaming text reveal ── */
  function v7_renderWalkthroughChapters(peel) {
    const wrap = document.getElementById("walkthroughChapters");
    if (!wrap) return;

    const sections = peel.sections || {};
    const titleEl = document.getElementById("walkthroughTitle");
    if (titleEl && state.currentPaper) {
      titleEl.textContent = state.currentPaper.title;
    }

    // Order of chapters + their transition lines
    const order = [
      { key: "what",         label: "Simple Explanation",   transition: "Paper peeled. Now let's see what came before it." },
      { key: "timeline",     label: "Historical Lineage",   transition: null /* lineage block follows */, hasLineage: true },
      { key: "fixes",        label: "What This Paper Fixes",transition: "Now let's understand its inner method." },
      { key: "architecture", label: "How It Works",         transition: "The method matters — but do the numbers back it up?" },
      { key: "results",      label: "Results & Benchmarks", transition: "One last question before we move on." },
      { key: "verdict",      label: "Should You Care?",     transition: null },
    ];

    const fragments = [];
    order.forEach((entry, idx) => {
      const section = sections[entry.key] || { title: entry.label, body: "Not extracted.", confidence: "low", evidence: [] };
      const confKey = String(section.confidence || "medium").toLowerCase();
      const confClass = confKey === "high" ? "conf-high" : confKey === "low" ? "conf-low" : "conf-medium";
      const evidenceHtmlStr = (section.evidence && section.evidence.length)
        ? `<div class="peel-evidence-strip">${section.evidence.map(e => `<span class="peel-evidence-pill">${escapeHtml((typeof e === "string" ? e : (e.label || e.location || "Evidence")))}</span>`).join("")}</div>`
        : "";
      const body = section.body || "Not extracted.";

      fragments.push(`
        <article class="peel-chapter" data-chapter="${entry.key}" data-chapter-index="${idx + 1}">
          <div class="peel-chapter-head">
            <span class="peel-chapter-index">Chapter ${String(idx + 1).padStart(2, "0")}</span>
            <h3 class="peel-chapter-title">${escapeHtml(section.title || entry.label)}</h3>
            <span class="conf-badge ${confClass}">${confKey} confidence</span>
          </div>
          <div class="peel-chapter-body">
            <div class="streaming-text" data-streaming-text>${v7_buildStreamingMarkup(body)}</div>
          </div>
          ${evidenceHtmlStr}
        </article>
      `);

      // If this chapter has lineage data, insert the 3 related-paper cards after it
      if (entry.hasLineage && peel.related_papers && peel.related_papers.length) {
        fragments.push(v7_buildLineageCardsHtml(peel.related_papers));
      }

      // Inter-chapter transition (italic centered line)
      if (entry.transition && idx < order.length - 1) {
        fragments.push(`<p class="peel-transition" data-transition>${escapeHtml(entry.transition)}</p>`);
      }
    });

    wrap.innerHTML = fragments.join("");
  }

  function v7_buildLineageCardsHtml(papers) {
    const cards = papers.slice(0, 3).map((rp, i) => {
      const yr = rp.year ? `${rp.year}` : "Year unknown";
      const authors = (rp.authors || []).slice(0, 3).join(", ") || "Authors unknown";
      return `
        <article class="peel-chapter lineage-card" data-lineage-index="${i + 1}">
          <div class="peel-chapter-head">
            <span class="peel-chapter-index">Prior Work · ${String(i + 1).padStart(2, "0")} · ${escapeHtml(yr)}</span>
            <h3 class="peel-chapter-title">${escapeHtml(rp.title || "Untitled")}</h3>
          </div>
          <p style="font-size:12px;color:var(--muted);margin-bottom:6px;">${escapeHtml(authors)}</p>
          <span class="lineage-source-ref">Related earlier paper</span>
          <div class="peel-chapter-body">
            <div class="streaming-text" data-streaming-text>${v7_buildStreamingMarkup([
              ["What it is", rp.summary || ""],
              ["What it had", rp.what_it_tried || ""],
              ["Its problem", rp.limitation || ""],
              ["How this paper solves it", rp.connection_to_this_paper || ""],
            ].filter(([_, t]) => t.trim()).map(([h, t]) => `${h}. ${t}`).join("\n\n"))}</div>
          </div>
        </article>
      `;
    }).join("");
    // Transparent: these aren't pulled from the paper's bibliography — they're
    // earlier work the analysis identified as relevant.
    return `
      <div class="lineage-block">
        <div class="lineage-eyebrow">Suggested earlier work · AI-identified</div>
        ${cards}
      </div>
    `;
  }

  /* Tokenize a body into word-spans for streaming reveal. Preserves paragraph breaks. */
  function v7_buildStreamingMarkup(text) {
    const safe = String(text || "").trim();
    if (!safe) return '<span class="word is-visible">&nbsp;</span>';

    // Detect existing paragraph breaks first; if absent, auto-break into ~3-sentence paragraphs.
    let paragraphs = safe.split(/\n\s*\n+/).map(p => p.trim()).filter(Boolean);
    if (paragraphs.length === 1) {
      // Split into sentences (period/!?/  followed by capital letter)
      const sentences = paragraphs[0].match(/[^.!?]+[.!?]+(\s+|$)/g) || [paragraphs[0]];
      paragraphs = [];
      const SENTENCES_PER_PARA = 3;
      for (let i = 0; i < sentences.length; i += SENTENCES_PER_PARA) {
        const chunk = sentences.slice(i, i + SENTENCES_PER_PARA).join(" ").trim();
        if (chunk) paragraphs.push(chunk);
      }
    }

    return paragraphs.map(p => {
      const words = p.split(/\s+/).filter(Boolean);
      const wordSpans = words.map(w => `<span class="word">${escapeHtml(w)}</span>`).join(" ");
      return `<p>${wordSpans}</p>`;
    }).join("");
  }

  /* Stream a chapter's words in over time — tutor cadence (per-word interval).
     Slow enough to clearly read as a typewriter, fast enough to never exceed ~6s. */
  function v7_streamChapter(chapterEl) {
    if (!chapterEl || chapterEl.dataset.streamed === "1") return;
    chapterEl.dataset.streamed = "1";
    chapterEl.classList.add("is-active");
    const wordEls = chapterEl.querySelectorAll(".streaming-text .word");
    if (!wordEls.length) return;
    // Reduced motion: just reveal everything
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      wordEls.forEach(w => w.classList.add("is-visible"));
      return;
    }
    const total = wordEls.length;
    // 1 word per tick for short chapters, 2 per tick for long — keeps cadence
    // visible while capping at ~5–6s.
    const PER_TICK = total > 200 ? 2 : 1;
    const TICK_MS  = 38;
    let i = 0;
    function tick() {
      const end = Math.min(i + PER_TICK, total);
      for (; i < end; i++) wordEls[i].classList.add("is-visible");
      if (i >= total) {
        chapterEl.classList.add("is-streamed");
        return;
      }
      window.setTimeout(tick, TICK_MS);
    }
    // Small initial delay so the chapter heading reads first, then text starts.
    window.setTimeout(tick, 220);
  }

  /* IntersectionObserver: stream a chapter when it enters view; reveal CTA when last chapter is in view */
  function v7_setupChapterReveal() {
    if (v7.chapterObserver) v7.chapterObserver.disconnect();
    const wrap = document.getElementById("walkthroughChapters");
    if (!wrap) return;
    const chapters = wrap.querySelectorAll(".peel-chapter");
    const transitions = wrap.querySelectorAll(".peel-transition");
    if (!chapters.length) return;

    let lastSeenIndex = -1;
    v7.chapterObserver = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          if (e.target.classList.contains("peel-transition")) {
            e.target.classList.add("is-visible");
          } else {
            v7_streamChapter(e.target);
            const idx = Number(e.target.dataset.chapterIndex || e.target.dataset.lineageIndex || 0);
            if (idx > lastSeenIndex) lastSeenIndex = idx;
            // Reveal stage 2 CTA in two beats: promise text first, then button
            if (e.target.dataset.chapter === "verdict") {
              v7_revealCta("ctaToArch");
            }
          }
        }
      });
    }, { rootMargin: "0px 0px -25% 0px", threshold: 0.15 });

    chapters.forEach(c => v7.chapterObserver.observe(c));
    transitions.forEach(t => v7.chapterObserver.observe(t));

    // Eagerly stream the first chapter so the user sees text immediately
    if (chapters[0]) v7_streamChapter(chapters[0]);
  }

  /* ── Stage CTAs ── */
  function v7_setupStageCTAs() {
    const btnArch = document.getElementById("btnRevealArch");
    if (btnArch && !btnArch.dataset.bound) {
      btnArch.dataset.bound = "1";
      btnArch.addEventListener("click", () => v7_revealStage("architecture"));
    }
    const btnPeelArch = document.getElementById("btnPeelArch");
    if (btnPeelArch && !btnPeelArch.dataset.bound) {
      btnPeelArch.dataset.bound = "1";
      btnPeelArch.addEventListener("click", () => v7_peelArchOpen());
    }
    const btnMath = document.getElementById("btnRevealMath");
    if (btnMath && !btnMath.dataset.bound) {
      btnMath.dataset.bound = "1";
      btnMath.addEventListener("click", () => v7_revealStage("math"));
    }
    const btnChat = document.getElementById("btnRevealChat");
    if (btnChat && !btnChat.dataset.bound) {
      btnChat.dataset.bound = "1";
      btnChat.addEventListener("click", () => v7_revealStage("chat"));
    }
    const btnBackArch = document.getElementById("archBackBtn");
    if (btnBackArch && !btnBackArch.dataset.bound) {
      btnBackArch.dataset.bound = "1";
      btnBackArch.addEventListener("click", () => v7_peelArchClose());
    }
    v7_bindPillNav();
    // Chat form is bound by the legacy init() in DOMContentLoaded — don't double-bind.
  }

  function v7_revealStage(name) {
    // Already unlocked → this is just a "switch to that window" request
    if (v7.stagesUnlocked[name]) {
      v7_showStage(name);
      return;
    }
    v7.stagesUnlocked[name] = true;
    state.guidedPeelComplete = true; // unblock any legacy gate
    state.mathUnlocked = true;

    const ids = { architecture: "stageArchitecture", math: "stageMath", chat: "stageChat" };
    const stage = document.getElementById(ids[name]);
    if (!stage) return;
    stage.hidden = false;        // unlock (no longer "locked")
    v7_updatePillNav(name);

    // Trigger the stage-specific render
    if (name === "architecture") {
      v7_renderArchCanvas(v7.archGraph);
    } else if (name === "math") {
      const equations = state.currentPeel ? (state.currentPeel.math_peel || []) : [];
      v7_renderMathTutor(equations);
    } else if (name === "chat") {
      // chat content already pre-rendered; just focus the input
      setTimeout(() => {
        const input = document.getElementById("chatInput");
        if (input) input.focus();
      }, 400);
    }

    // Switch into the freshly-unlocked window
    v7_showStage(name);
  }

  /* Reveal a stage-CTA zone in two beats: promise text fades up, then the
     button slides in. Used by every "unlock next section" prompt. */
  function v7_revealCta(id, buttonDelay = 700) {
    const cta = document.getElementById(id);
    if (!cta || cta.classList.contains("is-ready")) return;
    cta.classList.add("is-ready");
    window.setTimeout(() => cta.classList.add("is-buttoned"), buttonDelay);
  }

  /* ── Deck model: show exactly one section window at a time ──
     Unlocked windows stay freely switchable — nothing freezes after
     completion, and only one is ever rendered so nothing overlaps. */
  const V7_STAGE_IDS = {
    walkthrough:  "stageWalkthrough",
    architecture: "stageArchitecture",
    math:         "stageMath",
    chat:         "stageChat",
  };

  function v7_showStage(name) {
    const targetId = V7_STAGE_IDS[name];
    const target = targetId && document.getElementById(targetId);
    if (!target || target.hidden) return; // locked or missing → ignore

    // Activate only the target; every other window is fully hidden (no overlap)
    Object.values(V7_STAGE_IDS).forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.toggle("is-active", id === targetId);
    });

    // Replay the emerge transition on each switch
    target.classList.remove("is-emerging");
    void target.offsetWidth; // force reflow so the animation restarts
    target.classList.add("is-emerging");

    // Each window opens at the top
    const flow = document.getElementById("tutorFlow");
    if (flow) flow.scrollTop = 0;
    // Also scroll the page itself to the top so architecture canvas is fully visible
    window.scrollTo({ top: 0, behavior: "smooth" });

    // Expose the active stage to CSS so per-window chrome (e.g. result-hero)
    // can show/hide cleanly without JS coordination.
    const resultScreen = document.getElementById("resultScreen");
    if (resultScreen) resultScreen.dataset.activeStage = name;

    v7.activeStage = name;
    v7_setPillActive(name);

    // Auto-play the architecture playback immediately when entering stage 2!
    if (name === "architecture") {
      // Replay from the beginning if it has already completed
      if (v7.archNodeOrder && v7.archStepIndex >= v7.archNodeOrder.length - 1) {
        v7.archStepIndex = 0;
        const firstId = v7.archNodeOrder[0];
        if (firstId) v7_focusArchNode(firstId);
        v7_updateArchNav();
      }
      setTimeout(() => v7_startArchAutoPlay(), 400);
    }
  }

  function v7_setPillActive(name) {
    const nav = document.getElementById("sectionPillNav");
    if (!nav) return;
    nav.querySelectorAll("[data-pill-stage]").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.pillStage === name);
    });
  }

  /* ── Section pill navigation ── */
  function v7_updatePillNav(justUnlocked) {
    const nav = document.getElementById("sectionPillNav");
    if (!nav) return;
    const stageIds = {
      walkthrough:  "stageWalkthrough",
      architecture: "stageArchitecture",
      math:         "stageMath",
      chat:         "stageChat",
    };
    nav.querySelectorAll("[data-pill-stage]").forEach(btn => {
      const s = btn.dataset.pillStage;
      const isUnlocked = !!v7.stagesUnlocked[s];
      btn.disabled = !isUnlocked;          // locked sections greyed out
    });
    // Nav is visible from the start so the 4-window structure is always clear
    nav.hidden = false;
    // highlight the just-unlocked stage
    if (justUnlocked) v7_setPillActive(justUnlocked);
  }

  function v7_bindPillNav() {
    const nav = document.getElementById("sectionPillNav");
    if (!nav || nav.dataset.pillBound) return;
    nav.dataset.pillBound = "1";

    // Toggle navigation expand/collapse on click/tap (ideal for tablet where hover is unavailable)
    nav.addEventListener("click", (e) => {
      const btn = e.target.closest(".pill-nav-btn");
      if (!btn) {
        nav.classList.toggle("is-expanded");
        e.stopPropagation();
      } else {
        nav.classList.remove("is-expanded");
      }
    });

    // Collapse when clicking outside the navigation drawer
    document.addEventListener("click", (e) => {
      if (!nav.contains(e.target)) {
        nav.classList.remove("is-expanded");
      }
    });

    nav.querySelectorAll("[data-pill-stage]").forEach(btn => {
      btn.addEventListener("click", () => {
        if (btn.disabled) return;          // locked section — not switchable yet
        v7_showStage(btn.dataset.pillStage); // unlocked → free switch, no freeze
      });
    });
  }

  /* ── Tutor architecture canvas (Phase 3.3) ── */
  const SVG_NS = "http://www.w3.org/2000/svg";

  function v7_archTextSource(graph) {
    const paper = state.currentPaper || {};
    const peel = state.currentPeel || {};
    const sectionText = peel.sections && peel.sections.architecture ? peel.sections.architecture.body : "";
    const labels = []
      .concat((graph.nodes || []).map(n => n.label || n.id || ""))
      .concat((graph.expanded_nodes || []).map(n => n.label || n.id || ""))
      .join(" ");
    return `${paper.title || ""} ${paper.abstract || ""} ${sectionText || ""} ${labels}`.toLowerCase();
  }

  function v7_archKind(graph) {
    const text = v7_archTextSource(graph);
    if (/(transformer|self-attention|multi-head|encoder|decoder|attention is all you need|positional encoding)/i.test(text)) return "transformer";
    if (/(cnn|convolution|convolutional|pooling|feature map|kernel|image classification|vision)/i.test(text)) return "cnn";
    return "generic";
  }

  function v7_archTypeClass(type) {
    return ({
      attention: "is-attention",
      input: "is-input",
      output: "is-output",
      loss: "is-loss",
      math: "is-math",
      memory: "is-memory",
      norm: "is-norm",
      data: "is-data",
    })[String(type || "module").toLowerCase()] || "";
  }

  function v7_svg(tag, attrs = {}, text = null) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      if (key === "className") node.setAttribute("class", value);
      else if (key === "style") node.setAttribute("style", value);
      else node.setAttribute(key, value);
    });
    if (text !== null) node.textContent = text;
    return node;
  }

  // Wrap helper to break a string into lines at a given font + max chars/line.
  function v7_wrapLines(text, maxChars) {
    const words = String(text || "").split(/\s+/).filter(Boolean);
    const lines = [];
    let line = "";
    words.forEach(word => {
      const next = line ? `${line} ${word}` : word;
      if (next.length > maxChars && line) { lines.push(line); line = word; }
      else { line = next; }
    });
    if (line) lines.push(line);
    return lines;
  }

  /* Dynamic auto-fit label: shrinks the font until the wrapped text fits inside
     the node box (both width and height). Works for any architecture size —
     small diagrams get big text, large diagrams scale down, nothing overflows. */
  function v7_wrapSvgText(parent, text, x, y, options = {}) {
    const {
      fontSize = 21,        // starting (max) font in viewBox units
      boxW = 200,           // node width — text must fit inside
      boxH = 80,            // node height budget for the label
      maxLines = 2,
      className = "tutor-node-label",
      anchor = "middle",
      delay = 0,
    } = options;

    const CHAR_W = 0.56;    // avg glyph width as a fraction of font size
    const padX = Math.max(16, fontSize * 0.9);
    const usableW = Math.max(40, boxW - padX);

    let f = fontSize;
    let lines = [];
    // Step the font down until the longest line fits the width AND the stack
    // fits the height (≤ maxLines).
    for (; f >= 9; f -= 1) {
      const maxChars = Math.max(3, Math.floor(usableW / (f * CHAR_W)));
      lines = v7_wrapLines(text, maxChars);
      const longest = lines.reduce((m, l) => Math.max(m, l.length), 0);
      const fitsW = longest * f * CHAR_W <= usableW;
      const fitsH = lines.length * (f * 1.18) <= boxH;
      if (fitsW && lines.length <= maxLines && fitsH) break;
    }

    // Hard cap on line count (ellipsis the last line if still too many)
    const visible = lines.slice(0, maxLines);
    if (lines.length > maxLines && visible.length) {
      visible[visible.length - 1] = `${visible[visible.length - 1].replace(/[.,]$/, "")}…`;
    }

    const lineHeight = f * 1.18;
    const t = v7_svg("text", {
      x, y,
      class: className,
      "text-anchor": anchor,
      style: `--label-delay:${delay}ms; font-size:${f.toFixed(1)}px;`,
    });
    const startY = y - ((visible.length - 1) * lineHeight) / 2;
    visible.forEach((item, i) => {
      const span = v7_svg("tspan", { x, dy: i === 0 ? 0 : lineHeight }, item);
      if (i === 0) span.setAttribute("y", startY);
      t.appendChild(span);
    });
    parent.appendChild(t);
    return t;
  }

  function v7_transformerBlueprint(graph) {
    const nodeExplanations = {
      source_tokens: "The source sentence is broken into tokens. The Transformer never sees raw text directly; it works with learned vectors for these tokens.",
      source_embedding: "Each source token becomes a dense vector. This gives the model a numeric representation it can move through attention and feed-forward layers.",
      positional_encoding: "Because attention has no built-in order, positional encodings inject where each token sits in the sequence. Without this, the model would struggle to tell 'dog bites man' from 'man bites dog'.",
      encoder_attention: "Encoder self-attention lets every source token look at every other source token. This is where long-range context is mixed without recurrence.",
      encoder_ffn: "The feed-forward network transforms each position after attention has mixed context. Think of it as per-token reasoning after the model has gathered information.",
      encoder_norm: "Residual connections and layer normalization stabilize the stack. They keep gradients flowing and make deep encoder layers trainable.",
      memory: "The encoder output becomes contextual memory. The decoder later reads from this memory when generating the target sequence.",
      target_shifted: "The decoder receives the target sequence shifted right, so during training it predicts the next token rather than copying the current one.",
      decoder_masked_attention: "Masked self-attention lets the decoder look at earlier generated tokens while blocking future tokens.",
      decoder_cross_attention: "Encoder-decoder attention connects the generated target side to the source-side memory. This is where translation alignment happens.",
      decoder_ffn: "The decoder feed-forward network refines each generated position after both masked attention and source attention.",
      prediction_head: "The linear layer and softmax turn decoder states into probabilities over the vocabulary.",
      q_projection: "Queries are the questions a token asks about what information it needs.",
      k_projection: "Keys are the labels other tokens expose so they can be matched against the query.",
      v_projection: "Values are the actual information that gets mixed after attention weights are computed.",
      score_matrix: "The dot product QK^T measures how strongly each token should attend to every other token.",
      scale_softmax: "Scaling by sqrt(d_k) keeps scores numerically stable, and softmax turns them into a probability-like distribution.",
      weighted_values: "The attention weights choose and blend value vectors. This produces the contextual output for each token.",
      concat_heads: "Multiple heads are concatenated so the model can combine different attention patterns.",
      output_projection: "The output projection mixes all heads back into the model dimension used by the next layer.",
    };
    return {
      kind: "transformer",
      title: "Transformer architecture blueprint",
      defaultFocus: "encoder_attention",
      defaultPeel: "attention",
      // Wide, compact layout (~2.55:1) — fits the full-width canvas above the
      // dock without clipping, while keeping blocks large. Each zone is a single
      // vertical stack; data flows straight down a column then across columns.
      viewBox: [0, 0, 2100, 820],
      groups: [
        { id: "input_zone",   label: "Input",                x: 40,   y: 70,  w: 290, h: 230, caption: "source tokens" },
        { id: "encoder_zone", label: "Encoder stack (N=6)",  x: 410,  y: 70,  w: 380, h: 680, caption: "context builder" },
        { id: "memory_zone",  label: "Encoder memory",       x: 870,  y: 420, w: 300, h: 220, caption: "shared context" },
        { id: "decoder_zone", label: "Decoder stack (N=6)",  x: 1250, y: 70,  w: 430, h: 680, caption: "autoregressive generator" },
        { id: "output_zone",  label: "Prediction",           x: 1760, y: 540, w: 300, h: 210, caption: "vocabulary" },
      ],
      nodes: [
        { id: "source_tokens",           label: "Source tokens",             subtitle: "x1 ... xn",      type: "input",   x: 75,   y: 122, w: 220, h: 90 },
        { id: "source_embedding",        label: "Input embedding",           subtitle: "token vectors",  type: "data",    x: 440,  y: 120, w: 320, h: 82 },
        { id: "positional_encoding",     label: "Positional encoding",       subtitle: "order signal",   type: "math",    x: 440,  y: 222, w: 320, h: 82 },
        { id: "encoder_attention",       label: "Multi-head self-attention", subtitle: "global context", type: "attention", peel: "attention", x: 440, y: 324, w: 320, h: 82 },
        { id: "encoder_norm",            label: "Add + Norm",                subtitle: "residual path",  type: "norm",    x: 440,  y: 426, w: 320, h: 82 },
        { id: "encoder_ffn",             label: "Feed forward",              subtitle: "position-wise",  type: "module",  x: 440,  y: 528, w: 320, h: 82 },
        { id: "encoder_norm_2",          label: "Add + Norm",                subtitle: "stable stack",   type: "norm",    x: 440,  y: 630, w: 320, h: 82 },
        { id: "memory",                  label: "Contextual memory",         subtitle: "encoder output", type: "memory",  x: 905,  y: 470, w: 230, h: 110 },
        { id: "target_shifted",          label: "Shifted target",            subtitle: "y<t",            type: "input",   x: 1290, y: 120, w: 350, h: 88 },
        { id: "target_embedding",        label: "Output embedding",          subtitle: "target vectors", type: "data",    x: 1290, y: 246, w: 350, h: 88 },
        { id: "decoder_masked_attention",label: "Masked self-attention",     subtitle: "no future peek", type: "attention", peel: "attention", x: 1290, y: 372, w: 350, h: 88 },
        { id: "decoder_cross_attention", label: "Encoder-decoder attention", subtitle: "reads memory",   type: "attention", peel: "attention", x: 1290, y: 498, w: 350, h: 88 },
        { id: "decoder_ffn",             label: "Feed forward",              subtitle: "token transform",type: "module",  x: 1290, y: 624, w: 350, h: 88 },
        { id: "prediction_head",         label: "Linear + softmax",          subtitle: "next token",     type: "output",  x: 1795, y: 600, w: 230, h: 110 },
      ],
      // Real Transformer data flow — no number badges, just clean directed arrows
      edges: [
        { from: "source_tokens", to: "source_embedding" },
        { from: "source_embedding", to: "positional_encoding" },
        { from: "positional_encoding", to: "encoder_attention" },
        { from: "encoder_attention", to: "encoder_norm" },
        { from: "encoder_norm", to: "encoder_ffn" },
        { from: "encoder_ffn", to: "encoder_norm_2" },
        { from: "encoder_norm_2", to: "memory" },
        { from: "target_shifted", to: "target_embedding" },
        { from: "target_embedding", to: "decoder_masked_attention" },
        { from: "decoder_masked_attention", to: "decoder_cross_attention" },
        { from: "memory", to: "decoder_cross_attention" },
        { from: "decoder_cross_attention", to: "decoder_ffn" },
        { from: "decoder_ffn", to: "prediction_head" },
      ],
      peels: {
        attention: {
          label: "Scaled dot-product attention peeled open",
          viewBox: [0, 0, 1380, 580],
          groups: [
            { id: "projection_zone", label: "Projection stage",       x: 40,  y: 100, w: 360, h: 330, caption: "make Q, K, V" },
            { id: "score_zone",      label: "Attention score stage",  x: 460, y: 68,  w: 420, h: 390, caption: "compare tokens" },
            { id: "mix_zone",        label: "Value mixing",           x: 942, y: 100, w: 390, h: 330, caption: "blend information" },
          ],
          nodes: [
            { id: "input_states",     label: "Input states",     subtitle: "token vectors",    type: "input",    x: 68,  y: 240, w: 130, h: 68 },
            { id: "q_projection",     label: "Q projection",     subtitle: "what do I need?",  type: "math",     x: 240, y: 148, w: 130, h: 64 },
            { id: "k_projection",     label: "K projection",     subtitle: "what do I offer?", type: "math",     x: 240, y: 240, w: 130, h: 64 },
            { id: "v_projection",     label: "V projection",     subtitle: "content to pass",  type: "math",     x: 240, y: 332, w: 130, h: 64 },
            { id: "score_matrix",     label: "QK^T scores",      subtitle: "pairwise match",   type: "attention",x: 502, y: 158, w: 150, h: 70 },
            { id: "scale_softmax",    label: "Scale + softmax",  subtitle: "attention weights",type: "math",     x: 684, y: 158, w: 150, h: 70 },
            { id: "weighted_values",  label: "Weights × V",      subtitle: "context mix",      type: "attention",x: 684, y: 308, w: 150, h: 70 },
            { id: "concat_heads",     label: "Concat heads",     subtitle: "merge views",      type: "module",   x: 982, y: 202, w: 145, h: 68 },
            { id: "output_projection",label: "Output projection", subtitle: "back to model dim",type: "output",  x: 1165,y: 202, w: 135, h: 68 },
          ],
          edges: [
            { from: "input_states", to: "q_projection", label: "Q" },
            { from: "input_states", to: "k_projection", label: "K" },
            { from: "input_states", to: "v_projection", label: "V" },
            { from: "q_projection", to: "score_matrix", label: "1" },
            { from: "k_projection", to: "score_matrix", label: "2" },
            { from: "score_matrix", to: "scale_softmax", label: "3" },
            { from: "scale_softmax", to: "weighted_values", label: "4" },
            { from: "v_projection", to: "weighted_values", label: "5" },
            { from: "weighted_values", to: "concat_heads", label: "6" },
            { from: "concat_heads", to: "output_projection", label: "7" },
          ],
        },
      },
      dataFlowSteps: [
        "Tokens become embeddings, then positional encodings add sequence order.",
        "Encoder self-attention lets every source token read the entire source sentence.",
        "Feed-forward layers refine each position after attention has mixed context.",
        "The encoder output becomes memory that the decoder can query.",
        "Masked decoder attention reads previous target tokens without seeing the future.",
        "Cross-attention aligns decoder states with encoder memory.",
        "Linear + softmax converts the final decoder state into next-token probabilities.",
      ],
      nodeExplanations,
    };
  }

  function v7_cnnBlueprint() {
    const nodeExplanations = {
      input_image: "The raw image enters as a grid of pixel values. Early CNN layers preserve spatial layout so nearby pixels can be interpreted together.",
      conv_1: "The first convolution applies learned kernels across the image. Each kernel detects a local pattern such as an edge, corner, or color transition.",
      pool_1: "Pooling reduces spatial size while keeping strong signals. This makes the representation smaller and more tolerant to small shifts.",
      conv_2: "Deeper convolutional layers combine earlier edges into more complex visual parts.",
      pool_2: "The second pooling stage compresses the feature maps again so classification can focus on high-level evidence.",
      flatten: "Flattening converts stacked feature maps into a vector for dense classification layers.",
      dense: "The fully connected layer combines the extracted features to decide which class is most likely.",
      output_class: "The output layer turns classifier scores into class probabilities.",
      kernel_window: "A kernel is a small learned filter that slides over local image patches.",
      feature_maps: "Feature maps are the activation grids produced by filters. Bright regions mean the filter found its pattern there.",
      activation: "The activation function keeps useful signals and introduces non-linearity.",
      classifier_weights: "Classifier weights connect visual features to final labels.",
    };
    return {
      kind: "cnn",
      title: "CNN architecture blueprint",
      defaultFocus: "conv_1",
      defaultPeel: "cnn",
      viewBox: [0, 0, 1420, 600],
      groups: [
        { id: "image_zone", label: "Input image", x: 43, y: 208, w: 168, h: 144, caption: "pixels" },
        { id: "feature_zone", label: "Feature extraction", x: 264, y: 88, w: 672, h: 396, caption: "convolution + pooling" },
        { id: "classification_zone", label: "Classification", x: 996, y: 112, w: 360, h: 348, caption: "dense decision head" },
      ],
      nodes: [
        { id: "input_image", label: "Input image", subtitle: "H x W x C", type: "input", x: 75, y: 256, w: 106, h: 84 },
        { id: "conv_1", label: "Conv layer 1", subtitle: "kernels", type: "attention", peel: "cnn", x: 300, y: 172, w: 144, h: 78 },
        { id: "pool_1", label: "Pooling", subtitle: "downsample", type: "module", x: 492, y: 172, w: 128, h: 70 },
        { id: "conv_2", label: "Conv layer 2", subtitle: "higher features", type: "attention", peel: "cnn", x: 657, y: 172, w: 144, h: 78 },
        { id: "pool_2", label: "Pooling", subtitle: "compact maps", type: "module", x: 657, y: 319, w: 144, h: 70 },
        { id: "flatten", label: "Flatten", subtitle: "vector", type: "data", x: 1020, y: 220, w: 108, h: 110 },
        { id: "dense", label: "Fully connected", subtitle: "classifier", type: "module", x: 1170, y: 158, w: 132, h: 70 },
        { id: "output_class", label: "Output", subtitle: "probabilities", type: "output", x: 1170, y: 302, w: 132, h: 70 },
      ],
      edges: [
        { from: "input_image", to: "conv_1", label: "1" },
        { from: "conv_1", to: "pool_1", label: "2" },
        { from: "pool_1", to: "conv_2", label: "3" },
        { from: "conv_2", to: "pool_2", label: "4" },
        { from: "pool_2", to: "flatten", label: "5" },
        { from: "flatten", to: "dense", label: "6" },
        { from: "dense", to: "output_class", label: "7" },
      ],
      peels: {
        cnn: {
          label: "Convolutional feature extractor peeled open",
          viewBox: [0, 0, 1340, 570],
          groups: [
            { id: "local_zone", label: "Local pattern detection", x: 43, y: 109, w: 395, h: 321, caption: "kernel slides over image" },
            { id: "map_zone", label: "Feature map stack", x: 502, y: 95, w: 383, h: 345, caption: "many filters, many maps" },
            { id: "head_zone", label: "Decision head", x: 945, y: 119, w: 335, h: 297, caption: "features to classes" },
          ],
          nodes: [
            { id: "image_patch", label: "Image patch", subtitle: "local window", type: "input", x: 83, y: 228, w: 124, h: 83 },
            { id: "kernel_window", label: "Learned kernel", subtitle: "shared filter", type: "math", x: 265, y: 228, w: 127, h: 83 },
            { id: "feature_maps", label: "Feature maps", subtitle: "filter responses", type: "attention", x: 550, y: 176, w: 143, h: 74 },
            { id: "activation", label: "Activation", subtitle: "non-linearity", type: "module", x: 717, y: 176, w: 124, h: 74 },
            { id: "pooled_maps", label: "Pooled maps", subtitle: "compressed", type: "module", x: 634, y: 321, w: 136, h: 69 },
            { id: "classifier_weights", label: "Dense weights", subtitle: "feature voting", type: "math", x: 987, y: 197, w: 127, h: 74 },
            { id: "class_scores", label: "Class scores", subtitle: "logits", type: "output", x: 1143, y: 197, w: 110, h: 74 },
          ],
          edges: [
            { from: "image_patch", to: "kernel_window", label: "1" },
            { from: "kernel_window", to: "feature_maps", label: "2" },
            { from: "feature_maps", to: "activation", label: "3" },
            { from: "activation", to: "pooled_maps", label: "4" },
            { from: "pooled_maps", to: "classifier_weights", label: "5" },
            { from: "classifier_weights", to: "class_scores", label: "6" },
          ],
        },
      },
      dataFlowSteps: [
        "Pixels enter as an input image tensor.",
        "Convolutional kernels scan local patches and create feature maps.",
        "Pooling compresses feature maps while keeping strong responses.",
        "Deeper layers combine simple patterns into higher-level visual features.",
        "Flattening turns feature maps into a classifier-ready vector.",
        "Dense layers convert features into class scores.",
      ],
      nodeExplanations,
    };
  }

  function v7_genericBlueprint(graph) {
    const sourceNodes = (graph.nodes || []).slice(0, 8);
    const fallbackNodes = sourceNodes.length ? sourceNodes : [
      { id: "paper_input", label: "Paper input", type: "input" },
      { id: "method_core", label: "Method core", type: "module" },
      { id: "training_signal", label: "Training signal", type: "math" },
      { id: "paper_output", label: "Output", type: "output" },
    ];
    const viewW = 1120, viewH = 480;
    const step = Math.max(120, (viewW - 180) / Math.max(1, fallbackNodes.length - 1));
    const nodes = fallbackNodes.map((node, i) => ({
      id: node.id || `node_${i}`,
      label: node.label || node.id || `Block ${i + 1}`,
      subtitle: node.type || "module",
      type: node.type || (i === 0 ? "input" : i === fallbackNodes.length - 1 ? "output" : "module"),
      x: 56 + i * step,
      y: i % 2 ? 246 : 156,
      w: 120,
      h: 62,
    }));
    const ids = new Set(nodes.map(n => n.id));
    const edges = (graph.edges || []).filter(e => ids.has(e.from) && ids.has(e.to));
    const inferredEdges = nodes.slice(0, -1).map((node, i) => ({ from: node.id, to: nodes[i + 1].id, label: String(i + 1) }));
    const nodeExplanations = Object.assign({}, graph.node_explanations || {});
    nodes.forEach(node => {
      if (!nodeExplanations[node.id]) {
        nodeExplanations[node.id] = "This block is part of the extracted method pipeline. PaperLens will show stronger layer-level detail when the backend returns richer architecture evidence.";
      }
    });
    return {
      kind: "generic",
      title: "Extracted method blueprint",
      defaultFocus: nodes[0].id,
      defaultPeel: "generic",
      viewBox: [0, 0, viewW, viewH],
      groups: [
        { id: "method_zone", label: "Method pipeline", x: 28, y: 80, w: viewW - 56, h: 300, caption: "paper-extracted blocks" },
      ],
      nodes,
      edges: edges.length ? edges : inferredEdges,
      peels: {},
      dataFlowSteps: (graph.data_flow_steps || []).length ? graph.data_flow_steps : inferredEdges.map((_, i) => `Method step ${i + 1} moves information to the next block.`),
      nodeExplanations,
    };
  }

  function v7_archBlueprint(graph) {
    const kind = v7_archKind(graph || {});
    const blueprint = kind === "transformer"
      ? v7_transformerBlueprint(graph || {})
      : kind === "cnn"
        ? v7_cnnBlueprint(graph || {})
        : v7_genericBlueprint(graph || {});
    blueprint.rawGraph = graph || {};
    blueprint.nodeExplanations = Object.assign({}, blueprint.nodeExplanations || {}, (graph && graph.node_explanations) || {});
    if (graph && Array.isArray(graph.data_flow_steps) && graph.data_flow_steps.length > blueprint.dataFlowSteps.length) {
      blueprint.dataFlowSteps = graph.data_flow_steps;
    }
    return blueprint;
  }

  function v7_nodeCenter(node, side) {
    if (side === "left") return { x: node.x, y: node.y + node.h / 2 };
    if (side === "right") return { x: node.x + node.w, y: node.y + node.h / 2 };
    if (side === "top") return { x: node.x + node.w / 2, y: node.y };
    if (side === "bottom") return { x: node.x + node.w / 2, y: node.y + node.h };
    return { x: node.x + node.w / 2, y: node.y + node.h / 2 };
  }

  /* Clean orthogonal edge routing — single-bend "L" path with a small radius
     at the bend. Avoids the S-curves that previously snaked through nodes. */
  function v7_edgePath(from, to) {
    const fromCx = from.x + from.w / 2;
    const fromCy = from.y + from.h / 2;
    const toCx   = to.x + to.w / 2;
    const toCy   = to.y + to.h / 2;
    const dx     = toCx - fromCx;
    const dy     = toCy - fromCy;
    const horizontalDominant = Math.abs(dx) > Math.abs(dy);

    if (horizontalDominant) {
      const a = v7_nodeCenter(from, dx >= 0 ? "right" : "left");
      const b = v7_nodeCenter(to,   dx >= 0 ? "left"  : "right");
      // If endpoints are vertically aligned (±8px), draw a straight line — no curve at all
      if (Math.abs(a.y - b.y) <= 8) {
        return { d: `M ${a.x} ${a.y} L ${b.x} ${a.y}`, labelX: (a.x + b.x) / 2, labelY: a.y };
      }
      // Otherwise: go horizontal until midX, then vertical to b.y, then horizontal to b
      const midX = (a.x + b.x) / 2;
      const R = 14; // bend radius
      const sweep1 = b.y > a.y ? 1 : 0;
      const sweep2 = b.y > a.y ? 0 : 1;
      return {
        d: `M ${a.x} ${a.y} L ${midX - R} ${a.y} Q ${midX} ${a.y} ${midX} ${a.y + (b.y > a.y ? R : -R)} L ${midX} ${b.y - (b.y > a.y ? R : -R)} Q ${midX} ${b.y} ${midX + R} ${b.y} L ${b.x} ${b.y}`,
        labelX: midX,
        labelY: (a.y + b.y) / 2,
        _unused: [sweep1, sweep2],
      };
    }

    // Vertical-dominant — same idea, swapped
    const a = v7_nodeCenter(from, dy >= 0 ? "bottom" : "top");
    const b = v7_nodeCenter(to,   dy >= 0 ? "top"    : "bottom");
    if (Math.abs(a.x - b.x) <= 8) {
      return { d: `M ${a.x} ${a.y} L ${a.x} ${b.y}`, labelX: a.x, labelY: (a.y + b.y) / 2 };
    }
    const midY = (a.y + b.y) / 2;
    const R = 14;
    return {
      d: `M ${a.x} ${a.y} L ${a.x} ${midY - R} Q ${a.x} ${midY} ${a.x + (b.x > a.x ? R : -R)} ${midY} L ${b.x - (b.x > a.x ? R : -R)} ${midY} Q ${b.x} ${midY} ${b.x} ${midY + R} L ${b.x} ${b.y}`,
      labelX: (a.x + b.x) / 2,
      labelY: midY,
    };
  }

  function v7_drawBlueprint(svg, blueprint, mode = "overview") {
    svg.innerHTML = "";
    const [x, y, w, h] = blueprint.viewBox || [0, 0, 1100, 500];
    // Pad viewBox so zone titles (now placed above the rect) and node labels never clip
    const PAD = 48;
    svg.setAttribute("viewBox", `${x - PAD} ${y - PAD} ${w + PAD * 2} ${h + PAD * 2}`);
    // No explicit width/height — CSS sizes the SVG to fill its wrap; preserveAspectRatio handles scaling
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.dataset.archMode = mode;

    const defs = v7_svg("defs");
    defs.innerHTML = `
      <marker id="tutor-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" fill="rgba(168,196,240,0.68)"></path>
      </marker>
      <linearGradient id="arch-blueprint-fill" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="rgba(168,196,240,0.13)"></stop>
        <stop offset="100%" stop-color="rgba(245,230,204,0.045)"></stop>
      </linearGradient>
    `;
    svg.appendChild(defs);

    // ── Dynamic type scale ──
    // Font sizes are derived from the blueprint's own coordinate width so the
    // on-screen size stays consistent whether the architecture is small or huge.
    const vbW = w || 2100;
    const NODE_FONT = Math.max(12, Math.min(30, vbW / 95));   // node label (max; auto-fit shrinks)
    const ZONE_FONT = Math.max(10, Math.min(20, vbW / 130));  // zone title
    const CAP_FONT  = ZONE_FONT * 0.82;                        // zone caption
    const titleGap  = ZONE_FONT + 8;                           // space above zone for its title

    // Slower stagger — gives a "tutor pointing at each piece" feeling
    (blueprint.groups || []).forEach((group, i) => {
      const g = v7_svg("g", {
        class: "tutor-blueprint-zone",
        style: `--zone-delay:${i * 260}ms`,
        "data-zone-index": String(i),
      });
      g.appendChild(v7_svg("rect", {
        x: group.x, y: group.y, width: group.w, height: group.h, rx: 22, ry: 22,
        class: "tutor-blueprint-zone-rect",
      }));
      // Caption sits on its own line ABOVE the title — never on the same line,
      // so long captions can't collide with the title regardless of zone width.
      g.appendChild(v7_svg("text", {
        x: group.x + 4,
        y: group.y - titleGap * 0.45,
        class: "tutor-blueprint-zone-title",
        style: `font-size:${ZONE_FONT.toFixed(1)}px;`,
      }, String(group.label || "").toUpperCase()));
      if (group.caption) {
        g.appendChild(v7_svg("text", {
          x: group.x + 4,
          y: group.y - titleGap * 1.4,
          class: "tutor-blueprint-zone-caption",
          "text-anchor": "start",
          style: `font-size:${CAP_FONT.toFixed(1)}px;`,
        }, String(group.caption || "").toUpperCase()));
      }
      svg.appendChild(g);
    });

    const nodeMap = new Map((blueprint.nodes || []).map(node => [node.id, node]));
    (blueprint.edges || []).forEach((edge, i) => {
      const from = nodeMap.get(edge.from);
      const to = nodeMap.get(edge.to);
      if (!from || !to) return;
      const pathInfo = v7_edgePath(from, to);
      const edgeGroup = v7_svg("g", {
        class: "tutor-flow-edge-group",
        "data-edge-from": edge.from,
        "data-edge-to": edge.to,
        // Edges start after nodes are mostly laid down — clearer storytelling
        style: `--edge-delay:${2400 + i * 220}ms`,
      });
      edgeGroup.appendChild(v7_svg("path", {
        d: pathInfo.d,
        class: "tutor-edge tutor-blueprint-edge",
        "marker-end": "url(#tutor-arrow)",
      }));
      if (edge.label) {
        const badge = v7_svg("g", { class: "tutor-edge-badge" });
        badge.appendChild(v7_svg("circle", { cx: pathInfo.labelX, cy: pathInfo.labelY, r: 11 }));
        badge.appendChild(v7_svg("text", { x: pathInfo.labelX, y: pathInfo.labelY + 4, "text-anchor": "middle" }, edge.label));
        edgeGroup.appendChild(badge);
      }
      svg.appendChild(edgeGroup);
    });

    (blueprint.nodes || []).forEach((node, i) => {
      const g = v7_svg("g", {
        class: `tutor-node-group tutor-blueprint-node ${node.peel ? "has-peel" : ""}`,
        "data-node-id": node.id,
        "data-peel-id": node.peel || "",
        // Nodes start after zones, slow stagger so each block reads as a beat
        style: `--node-delay:${800 + i * 240}ms;--label-delay:${1400 + i * 240}ms`,
      });
      g.appendChild(v7_svg("rect", {
        x: node.x, y: node.y, width: node.w, height: node.h, rx: 16, ry: 16,
        class: `tutor-node-rect ${v7_archTypeClass(node.type)}`,
      }));
      // Label — auto-fits font to the box; reserve a strip at the bottom for the subtitle
      const subFont = Math.max(9, Math.min(NODE_FONT * 0.6, node.h * 0.2));
      const labelBudgetH = node.subtitle ? node.h - subFont * 2.4 : node.h - 16;
      v7_wrapSvgText(g, node.label || node.id, node.x + node.w / 2, node.y + node.h / 2 - (node.subtitle ? subFont * 0.9 : 0), {
        fontSize: NODE_FONT,
        boxW: node.w,
        boxH: Math.max(24, labelBudgetH),
        maxLines: 2,
        delay: 1400 + i * 240,
      });
      if (node.subtitle) {
        g.appendChild(v7_svg("text", {
          x: node.x + node.w / 2,
          y: node.y + node.h - subFont * 0.9,
          class: "tutor-node-sublabel",
          "text-anchor": "middle",
          style: `--label-delay:${1600 + i * 240}ms; font-size:${subFont.toFixed(1)}px;`,
        }, String(node.subtitle).toUpperCase()));
      }
      g.addEventListener("click", () => {
        v7_stopArchAutoPlay();
        v7_focusArchNode(node.id);
        // Reveal peel CTA on manual interaction too + unlock data-flow steps
        const peelCta = document.getElementById("archPeelCta");
        if (peelCta) setTimeout(() => peelCta.classList.add("is-ready"), 600);
        v7_markArchComplete();
      });
      svg.appendChild(g);
    });
  }

  function v7_renderArchCanvas(graph) {
    const svg = document.getElementById("architectureCanvas");
    if (!svg) return;
    v7.archExpanded = false;
    v7.archComplete = false;   // data-flow steps stay locked until the tour finishes
    v7_stopArchAutoPlay();
    v7.archBlueprint = v7_archBlueprint(graph || {});
    v7.archSelectedPeel = v7.archBlueprint.defaultPeel || null;
    v7_drawBlueprint(svg, v7.archBlueprint, "overview");

    const stageText = document.getElementById("archStageText");
    if (stageText) stageText.textContent = "Drawing full blueprint view.";

    // Initialize step navigation
    v7_initArchNav(v7.archBlueprint);
    v7_bindArchNav();

    // Hide peel CTA until tour finishes (or user stops auto-play)
    const peelCta = document.getElementById("archPeelCta");
    if (peelCta) {
      peelCta.classList.remove("is-ready");
      const btn = document.getElementById("btnPeelArch");
      if (btn) {
        const label = v7.archBlueprint.kind === "generic" ? "Peel this open" : "Peel the block";
        btn.lastChild.nodeValue = ` ${label}`;
      }
    }

    v7_renderArchFlow(v7.archBlueprint);

    // Focus first node immediately, then kick off auto-play tour
    const firstId = v7.archNodeOrder[0] || (v7.archBlueprint.nodes[0] && v7.archBlueprint.nodes[0].id);
    if (firstId) {
      setTimeout(() => {
        v7_focusArchNode(firstId);
        v7_updateArchNav();
        // Auto-play starts after the blueprint has fully drawn in
        setTimeout(() => v7_startArchAutoPlay(), 1200);
      }, 900);
    }
  }

  function v7_renderArchFlow(blueprint) {
    const ol = document.getElementById("flowSteps");
    if (!ol) return;
    const steps = (blueprint.dataFlowSteps || blueprint.data_flow_steps || []).slice(0, 8);
    ol.innerHTML = steps.length
      ? steps.map((s, i) => `<li data-flow-index="${i}">${escapeHtml(s)}</li>`).join("")
      : '<li style="color:var(--faint)">No data-flow narration available.</li>';

    // Scroll-driven reveal, GATED on architecture completion. Steps only begin
    // animating in (block by block) once the architecture tour has finished
    // (i.e. the peel button has appeared) AND the panel is scrolled into view.
    if (v7.flowStepObserver) v7.flowStepObserver.disconnect();
    const lis = [...ol.querySelectorAll("li")];

    const revealStep = (li) => {
      if (li.classList.contains("is-visible")) return;
      const i = Number(li.dataset.flowIndex || 0);
      window.setTimeout(() => li.classList.add("is-visible"), i * 120);
    };

    if (!("IntersectionObserver" in window)) {
      lis.forEach(li => li.classList.add("is-visible"));
      return;
    }

    v7.flowStepObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        if (!v7.archComplete) return;   // gate: hold until architecture is done
        revealStep(entry.target);
        v7.flowStepObserver.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -15% 0px", threshold: 0.2 });
    lis.forEach(li => v7.flowStepObserver.observe(li));

    // When the architecture later completes, reveal any steps already in view.
    v7.revealFlowIfVisible = () => {
      const vh = window.innerHeight || document.documentElement.clientHeight;
      lis.forEach(li => {
        if (li.classList.contains("is-visible")) return;
        const r = li.getBoundingClientRect();
        if (r.top < vh * 0.85 && r.bottom > 0) {
          revealStep(li);
          if (v7.flowStepObserver) v7.flowStepObserver.unobserve(li);
        }
      });
    };
  }

  /* Architecture overview finished (peel button is showing) — unlock the
     data-flow steps so they can animate in on scroll. */
  function v7_markArchComplete() {
    v7.archComplete = true;
    if (typeof v7.revealFlowIfVisible === "function") v7.revealFlowIfVisible();
  }

  function v7_streamArchText(node, text) {
    if (!node) return;
    window.clearTimeout(v7.archTextTimer);
    const clean = String(text || "");
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.textContent = clean;
      return;
    }
    node.textContent = "";
    const chars = Array.from(clean);
    const chunkSize = clean.length > 360 ? 6 : 4;
    let idx = 0;
    const tick = () => {
      idx = Math.min(chars.length, idx + chunkSize);
      node.textContent = chars.slice(0, idx).join("");
      if (idx < chars.length) v7.archTextTimer = window.setTimeout(tick, 14);
    };
    tick();
  }

  function v7_focusArchNode(nodeId) {
    const svg = document.getElementById("architectureCanvas");
    if (!svg) return;
    const blueprint = v7.archExpanded && v7.activePeelBlueprint ? v7.activePeelBlueprint : v7.archBlueprint;
    if (!blueprint) return;
    const targetNode = (blueprint.nodes || []).find(n => n.id === nodeId);
    if (!targetNode) return;

    // Sync step index if user clicked directly on a node
    const orderIdx = v7.archNodeOrder.indexOf(nodeId);
    if (orderIdx !== -1 && orderIdx !== v7.archStepIndex) {
      v7.archStepIndex = orderIdx;
      v7_updateArchNav();
    }

    // Highlight focused node
    svg.querySelectorAll(".tutor-node-rect").forEach(r => r.classList.remove("is-focused"));
    const groupEl = svg.querySelector(`[data-node-id="${CSS.escape(nodeId)}"]`);
    if (groupEl) {
      const r = groupEl.querySelector(".tutor-node-rect");
      if (r) r.classList.add("is-focused");
    }

    // Mark active / muted edges and add particle flow
    svg.querySelectorAll(".arch-particle-group").forEach(pg => pg.remove());
    svg.querySelectorAll(".tutor-flow-edge-group").forEach(edge => {
      const touches = edge.dataset.edgeFrom === nodeId || edge.dataset.edgeTo === nodeId;
      edge.classList.toggle("is-active", touches);
      edge.classList.toggle("is-muted", !touches);
      if (touches) {
        const path = edge.querySelector(".tutor-blueprint-edge");
        if (path) {
          const d = path.getAttribute("d");
          if (d) v7_addEdgeParticles(edge, d);
        }
      }
    });

    if (targetNode.peel) {
      v7.archSelectedPeel = targetNode.peel;
      const btn = document.getElementById("btnPeelArch");
      if (btn && btn.lastChild) btn.lastChild.nodeValue = ` Peel ${targetNode.label || "this block"}`;
    }

    const title = document.getElementById("archNodeTitle");
    const body  = document.getElementById("archNodeBody");
    const explanation = (blueprint.nodeExplanations || {})[nodeId]
      || "PaperLens identified this layer as part of the paper's method flow. A richer backend peel can attach more exact evidence to this block.";
    if (title) title.textContent = targetNode.label || targetNode.id;
    v7_streamArchText(body, explanation);
  }

  /* Stage 2 of architecture: expand selected high-value block */
  function v7_peelArchOpen() {
    const svg = document.getElementById("architectureCanvas");
    const blueprint = v7.archBlueprint || v7_archBlueprint(v7.archGraph || {});
    if (!svg || !blueprint) return;
    const peelId = v7.archSelectedPeel || blueprint.defaultPeel;
    const peel = peelId && blueprint.peels ? blueprint.peels[peelId] : null;
    if (!peel) {
      const stageText = document.getElementById("archStageText");
      if (stageText) stageText.textContent = "This paper only exposed a single-level architecture view.";
      v7_revealCta("ctaToMath");
      return;
    }

    v7.archExpanded = true;
    const backBtn = document.getElementById("archBackBtn");
    if (backBtn) backBtn.hidden = false;
    v7.activePeelBlueprint = Object.assign({}, peel, {
      kind: blueprint.kind,
      defaultFocus: (peel.nodes[0] && peel.nodes[0].id) || blueprint.defaultFocus,
      dataFlowSteps: blueprint.dataFlowSteps,
      nodeExplanations: Object.assign({}, blueprint.nodeExplanations || {}),
    });
    v7_drawBlueprint(svg, v7.activePeelBlueprint, "peeled");

    const peelCta = document.getElementById("archPeelCta");
    if (peelCta) peelCta.classList.remove("is-ready");
    const stageText = document.getElementById("archStageText");
    if (stageText) stageText.textContent = "Peeled view - data flow inside the selected block.";
    const title = document.getElementById("archNodeTitle");
    if (title) title.textContent = peel.label || "Peeled architecture";
    const body = document.getElementById("archNodeBody");
    v7_streamArchText(body, "Now the block is opened into the operations that make it work. Follow the numbered arrows: the model projects representations, computes scores or features, transforms them, and returns a cleaner signal to the next layer.");

    const focus = v7.activePeelBlueprint.defaultFocus;
    // Re-init step nav for the peeled blueprint
    v7_initArchNav(v7.activePeelBlueprint);
    if (focus) {
      v7.archStepIndex = Math.max(0, v7.archNodeOrder.indexOf(focus));
      v7_updateArchNav();
      setTimeout(() => v7_focusArchNode(focus), 900);
    }
    setTimeout(() => v7_revealCta("ctaToMath"), 2400);
  }

  /* Return from peeled view to main overview blueprint */
  function v7_peelArchClose() {
    const svg = document.getElementById("architectureCanvas");
    if (!svg || !v7.archBlueprint) return;
    v7.archExpanded = false;
    v7.activePeelBlueprint = null;
    v7_drawBlueprint(svg, v7.archBlueprint, "overview");
    v7_initArchNav(v7.archBlueprint);
    v7_bindArchNav();
    const stageText = document.getElementById("archStageText");
    if (stageText) stageText.textContent = "Full blueprint view.";
    const peelCta = document.getElementById("archPeelCta");
    if (peelCta) {
      peelCta.classList.remove("is-ready");
      setTimeout(() => peelCta.classList.add("is-ready"), 1000);
    }
    const backBtn = document.getElementById("archBackBtn");
    if (backBtn) backBtn.hidden = true;
    // Re-focus the last known node
    const focusId = v7.archNodeOrder[v7.archStepIndex]
      || (v7.archBlueprint.nodes[0] && v7.archBlueprint.nodes[0].id);
    if (focusId) setTimeout(() => v7_focusArchNode(focusId), 200);
  }

  /* ── Architecture step navigation (Phase 5) ── */

  /** BFS-order node IDs so stepping follows the data flow naturally. */
  function v7_buildNodeOrder(blueprint) {
    const nodes = blueprint.nodes || [];
    const edges = blueprint.edges || [];
    if (!nodes.length) return [];
    const inDeg = {};
    const adj = {};
    nodes.forEach(n => { inDeg[n.id] = 0; adj[n.id] = []; });
    edges.forEach(e => {
      if (adj[e.from] !== undefined) adj[e.from].push(e.to);
      if (inDeg[e.to] !== undefined) inDeg[e.to]++;
    });
    const queue = nodes.filter(n => (inDeg[n.id] || 0) === 0).map(n => n.id);
    const visited = new Set(queue);
    const order = [...queue];
    while (queue.length) {
      const id = queue.shift();
      (adj[id] || []).forEach(next => {
        if (!visited.has(next)) {
          visited.add(next);
          queue.push(next);
          order.push(next);
        }
      });
    }
    // Append any disconnected nodes (cycles etc.)
    nodes.forEach(n => { if (!visited.has(n.id)) order.push(n.id); });
    return order;
  }

  function v7_initArchNav(blueprint) {
    v7.archNodeOrder = v7_buildNodeOrder(blueprint);
    v7.archStepIndex = 0;
    v7_updateArchNav();
  }

  function v7_updateArchNav() {
    const counter = document.getElementById("archNavCounter");
    const prevBtn = document.getElementById("archNavPrev");
    const nextBtn = document.getElementById("archNavNext");
    const total = v7.archNodeOrder.length;
    const i = v7.archStepIndex;
    if (counter) {
      const nodeId = v7.archNodeOrder[i] || "";
      const blueprint = v7.archExpanded && v7.activePeelBlueprint ? v7.activePeelBlueprint : v7.archBlueprint;
      const node = blueprint ? (blueprint.nodes || []).find(n => n.id === nodeId) : null;
      const label = node ? (node.label || node.id) : nodeId;
      counter.textContent = `${i + 1} / ${total}  ·  ${label.length > 22 ? label.slice(0, 21) + "…" : label}`;
    }
    if (prevBtn) prevBtn.disabled = i <= 0;
    if (nextBtn) nextBtn.disabled = i >= v7.archNodeOrder.length - 1;

    // Sequential scroll reveal gating: when step 3 / 14 (index >= 2) is reached:
    if (i >= 2) {
      // 1. Reveal "Peel Inside" CTA immediately
      const peelCta = document.getElementById("archPeelCta");
      if (peelCta) peelCta.classList.add("is-ready");

      // 2. Unlock and show "Data Flow" block on scroll
      v7_markArchComplete();

      // 3. Unlock and show "Math Peel" option on scroll further
      v7_revealCta("ctaToMath");
    }
  }

  function v7_bindArchNav() {
    const prevBtn = document.getElementById("archNavPrev");
    const nextBtn = document.getElementById("archNavNext");
    const autoBtn = document.getElementById("archNavAuto");
    if (prevBtn && !prevBtn.dataset.navBound) {
      prevBtn.dataset.navBound = "1";
      prevBtn.addEventListener("click", () => v7_stepArchNode(-1));
    }
    if (nextBtn && !nextBtn.dataset.navBound) {
      nextBtn.dataset.navBound = "1";
      nextBtn.addEventListener("click", () => v7_stepArchNode(+1));
    }
    if (autoBtn && !autoBtn.dataset.navBound) {
      autoBtn.dataset.navBound = "1";
      autoBtn.addEventListener("click", () => {
        if (v7.archAutoPlaying) v7_stopArchAutoPlay();
        else v7_startArchAutoPlay();
      });
    }
  }

  function v7_stepArchNode(dir) {
    v7_stopArchAutoPlay();
    const total = v7.archNodeOrder.length;
    v7.archStepIndex = Math.max(0, Math.min(total - 1, v7.archStepIndex + dir));
    const nodeId = v7.archNodeOrder[v7.archStepIndex];
    if (nodeId) v7_focusArchNode(nodeId);
    v7_updateArchNav();
  }

  function v7_startArchAutoPlay() {
    if (v7.archAutoPlaying) return; // Prevent duplicate timers
    v7.archAutoPlaying = true;
    const autoBtn = document.getElementById("archNavAuto");
    if (autoBtn) autoBtn.classList.add("is-playing");
    const step = () => {
      if (!v7.archAutoPlaying) return;
      const total = v7.archNodeOrder.length;
      if (v7.archStepIndex < total - 1) {
        v7.archStepIndex++;
        const nodeId = v7.archNodeOrder[v7.archStepIndex];
        if (nodeId) v7_focusArchNode(nodeId);
        v7_updateArchNav();
        v7.archAutoTimer = window.setTimeout(step, 2100);
      } else {
        v7_stopArchAutoPlay();
        // Fallback checks once the tour finishes
        const peelCta = document.getElementById("archPeelCta");
        if (peelCta) setTimeout(() => peelCta.classList.add("is-ready"), 800);
        v7_markArchComplete();
      }
    };
    v7.archAutoTimer = window.setTimeout(step, 2100);
  }

  function v7_stopArchAutoPlay() {
    v7.archAutoPlaying = false;
    window.clearTimeout(v7.archAutoTimer);
    const autoBtn = document.getElementById("archNavAuto");
    if (autoBtn) autoBtn.classList.remove("is-playing");
  }

  /** Place animated particle dots along an active edge path. */
  function v7_addEdgeParticles(edgeGroup, pathD) {
    // Remove any previous particles attached to this edge
    const existing = edgeGroup.dataset.particleId;
    if (existing) {
      const old = document.getElementById(existing);
      if (old) old.remove();
    }
    const uid = `apg_${Math.random().toString(36).slice(2, 8)}`;
    edgeGroup.dataset.particleId = uid;
    const pg = document.createElementNS(SVG_NS, "g");
    pg.setAttribute("id", uid);
    pg.setAttribute("class", "arch-particle-group");
    // Two staggered dots
    const offsets = [0, 0.52];
    offsets.forEach(offset => {
      const dur = 1.5;
      const circle = document.createElementNS(SVG_NS, "circle");
      circle.setAttribute("r", "3.2");
      circle.setAttribute("class", "arch-particle");
      const anim = document.createElementNS(SVG_NS, "animateMotion");
      anim.setAttribute("dur", `${dur}s`);
      anim.setAttribute("repeatCount", "indefinite");
      if (offset > 0) anim.setAttribute("begin", `${(offset * dur).toFixed(2)}s`);
      anim.setAttribute("path", pathD);
      anim.setAttribute("rotate", "auto");
      circle.appendChild(anim);
      pg.appendChild(circle);
    });
    if (edgeGroup.parentNode) edgeGroup.parentNode.insertBefore(pg, edgeGroup.nextSibling);
  }

  /* ── Math tutor (Phase 3.4) ── */
  function v7_renderMathTutor(equations) {
    const wrap = document.getElementById("mathTutor");
    if (!wrap) return;
    if (!equations.length) {
      wrap.innerHTML = `<p style="color:var(--muted)">No equations extracted for this paper.</p>`;
      return;
    }

    wrap.innerHTML = equations.map((eq, i) => {
      const symbolsHtml = (eq.symbols || []).map(s => `
        <div class="math-eq-symbol">
          <span class="math-eq-symbol-key">${escapeHtml(v7_prettySymbol(s.symbol || ""))}</span>
          <span class="math-eq-symbol-meaning">${escapeHtml(s.meaning || "")}</span>
        </div>
      `).join("");

      const metaCards = [
        ["Plain meaning",       eq.plain_meaning],
        ["Role in architecture", eq.role_in_architecture],
        ["Behavior if changed", eq.behavior_if_changed],
      ].filter(([_, v]) => v && String(v).trim()).map(([h, v]) => `
        <article data-meta>
          <strong>${escapeHtml(h)}</strong>
          <p>${escapeHtml(v)}</p>
        </article>
      `).join("");

      return `
        <section class="math-eq-card" data-eq-index="${i}">
          <div>
            <div class="math-eq-marker">Equation <strong>${String(i + 1).padStart(2, "0")}</strong></div>
            <div class="math-eq-location">${escapeHtml(eq.location || "Method")}</div>
          </div>
          <div class="math-eq-frame">
            <div class="math-eq-render" data-eq-latex="${escapeHtml(eq.latex || "")}"></div>
            <span class="math-eq-pen" aria-hidden="true"></span>
          </div>
          ${metaCards ? `<div class="math-eq-meta">${metaCards}</div>` : ""}
          ${symbolsHtml ? `<div class="math-eq-symbols" data-symbols>${symbolsHtml}</div>` : ""}
        </section>
      `;
    }).join("");

    function v7_prettySymbol(symbol) {
      return String(symbol || "")
        .replace(/\\?cdot/g, "·")
        .replace(/\\?sqrt\{([^}]+)\}/g, "√($1)")
        .replace(/\s+/g, " ")
        .trim();
    }

    function v7_plainMathFallback(latex) {
      let s = String(latex || "");
      // Collapse common LaTeX into clean readable plain math (never show raw code)
      for (let k = 0; k < 4; k++) {
        const before = s;
        s = s
          .replace(/\\operatorname\{([^}]+)\}/g, "$1")
          .replace(/\\text\{([^}]+)\}/g, "$1")
          .replace(/\\mathrm\{([^}]+)\}/g, "$1")
          .replace(/\\frac\{([^{}]+)\}\{([^{}]+)\}/g, "($1)/($2)")
          .replace(/\\sqrt\{([^{}]+)\}/g, "√($1)");
        if (s === before) break;
      }
      return s
        .replace(/\\cdot/g, "·")
        .replace(/\\times/g, "×")
        .replace(/\\left|\\right/g, "")
        .replace(/\\,|\\;|\\!/g, " ")
        .replace(/[{}]/g, "")
        .replace(/\\/g, "")
        .replace(/\s+/g, " ")
        .trim();
    }

    function v7_fixLatex(latex) {
      let s = String(latex || "");
      // Fix invalid KaTeX nesting that LLMs commonly generate:
      // \\text{\\operatorname{X}} -> \\operatorname{X} (can't nest \\operatorname inside \\text)
      s = s.replace(/\\text\{\\operatorname\{([^}]+)\}\}/g, "\\operatorname{$1}");
      // \text{\text{X}} → \text{X}
      s = s.replace(/\\text\{\\text\{([^}]+)\}\}/g, "\\text{$1}");
      s = s
        .replace(/\$/g, "")
        .replace(/[“”]/g, '"')
        .replace(/[‘’]/g, "'")
        .replace(/[·•]/g, " cdot ")
        .replace(/\s+/g, " ")
        .trim();

      // ── Unicode → LaTeX (the #1 source of KaTeX failures from weak models) ──
      // Square root written as a unicode glyph: √(d_k), √{d_k}, √d_k, √x
      s = s
        .replace(/√\s*\(([^)]+)\)/g, "\\sqrt{$1}")
        .replace(/√\s*\{([^}]+)\}/g, "\\sqrt{$1}")
        .replace(/√\s*([A-Za-z0-9](?:_\{?[A-Za-z0-9]+\}?)?)/g, "\\sqrt{$1}")
        .replace(/√/g, "\\surd ");
      // Common math unicode operators/relations/arrows/sets
      const uni = {
        "×": "\\times ", "÷": "\\div ", "∗": "*", "−": "-", "⋅": " \\cdot ",
        "≈": "\\approx ", "≠": "\\neq ", "≤": "\\leq ", "≥": "\\geq ",
        "≪": "\\ll ", "≫": "\\gg ", "∝": "\\propto ", "≡": "\\equiv ",
        "→": "\\rightarrow ", "←": "\\leftarrow ", "↔": "\\leftrightarrow ",
        "⇒": "\\Rightarrow ", "∑": "\\sum ", "∏": "\\prod ", "∫": "\\int ",
        "∈": "\\in ", "∉": "\\notin ", "⊂": "\\subset ", "⊆": "\\subseteq ",
        "∀": "\\forall ", "∃": "\\exists ", "∞": "\\infty ", "∂": "\\partial ",
        "∇": "\\nabla ", "±": "\\pm ", "∓": "\\mp ", "·": " \\cdot ",
        "θ": "\\theta ", "α": "\\alpha ", "β": "\\beta ", "γ": "\\gamma ",
        "δ": "\\delta ", "ε": "\\epsilon ", "λ": "\\lambda ", "μ": "\\mu ",
        "σ": "\\sigma ", "π": "\\pi ", "φ": "\\phi ", "ω": "\\omega ",
        "Σ": "\\Sigma ", "Π": "\\Pi ", "Δ": "\\Delta ", "Ω": "\\Omega ",
      };
      s = s.replace(/[×÷∗−⋅≈≠≤≥≪≫∝≡→←↔⇒∑∏∫∈∉⊂⊆∀∃∞∂∇±∓·θαβγδελμσπφωΣΠΔΩ]/g, ch => uni[ch] || ch);

      // Common LLM damage: glued command words, missing braces, or command names without backslashes.
      // CRITICAL: negative lookbehind (?<!\\) prevents double-escaping already-backslashed commands
      // (e.g. \cdot must NOT become \\cdot, which KaTeX renders as a newline).
      s = s
        .replace(/\\?softmax\b/gi, "__SOFTMAX__")
        .replace(/\\?Attention\b/g, "__ATTENTION__")
        .replace(/\\?Concat\b/g, "__CONCAT__")
        .replace(/(?<!\\)sqrtd_?\{?([A-Za-z0-9]+)\}?/gi, "\\sqrt{d_$1}")
        .replace(/(?<!\\)sqrt\s*d_?([A-Za-z0-9]+)/gi, "\\sqrt{d_$1}")
        .replace(/(?<!\\)sqrt\s*\{\s*([^}]+?)\s*\}/gi, "\\sqrt{$1}")
        .replace(/(?<!\\)([A-Za-z0-9_}\)])\s*cdot\s*([A-Za-z0-9_\\{(])/g, "$1 \\cdot $2")
        .replace(/(?<!\\)\bcdot\b/g, "\\cdot")
        .replace(/(?<!\\)\bfrac\b/g, "\\frac")
        .replace(/(?<!\\)\bpartial\b/g, "\\partial")
        .replace(/(?<!\\)\binfty\b/g, "\\infty")
        .replace(/(?<!\\)\b(alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)\b/g, "\\$1")
        .replace(/__SOFTMAX__/g, "\\operatorname{softmax}")
        .replace(/__ATTENTION__/g, "\\operatorname{Attention}")
        .replace(/__CONCAT__/g, "\\operatorname{Concat}");

      // Make the classic attention formula readable even when the provider omits the named left side.
      if (/\\operatorname\{softmax\}/.test(s) && /\bQ\b/.test(s) && /\bK\^T\b/.test(s) && /\bV\b/.test(s) && !/^\\operatorname\{Attention\}/.test(s)) {
        s = `\\operatorname{Attention}(Q,K,V) = ${s}`;
      }

      // FINAL de-nest pass — the substitutions above can produce invalid nesting
      // like \text{\operatorname{softmax}} (e.g. when the source had \text{softmax}).
      // Run repeatedly until stable so KaTeX never chokes on it.
      for (let k = 0; k < 4; k++) {
        const before = s;
        s = s
          .replace(/\\text\{\\operatorname\{([^}]+)\}\}/g, "\\operatorname{$1}")
          .replace(/\\operatorname\{\\operatorname\{([^}]+)\}\}/g, "\\operatorname{$1}")
          .replace(/\\text\{\\text\{([^}]+)\}\}/g, "\\text{$1}");
        if (s === before) break;
      }

      s = s
        .replace(/\s*\/\s*/g, " / ")
        .replace(/\s*=\s*/g, " = ")
        .replace(/\s+/g, " ")
        .trim();
      return s;
    }

    const renderEq = (host, latex) => {
      if (!latex) return;
      if (!(window.katex && window.katex.render)) {
        host.innerHTML = `<span class="math-render-plain">${escapeHtml(v7_plainMathFallback(v7_fixLatex(latex)))}</span>`;
        return;
      }
      // Pass 1: normalized LaTeX. Pass 2: a more aggressively sanitized version.
      // Pass 3: clean plain-math fallback (readable, NEVER raw code or red errors).
      const attempts = [
        v7_fixLatex(latex),
        v7_fixLatex(latex).replace(/\\operatorname\{([^}]+)\}/g, "\\mathrm{$1}").replace(/\\surd\s*/g, "\\sqrt{} "),
      ];
      for (const candidate of attempts) {
        try {
          window.katex.render(candidate, host, { throwOnError: true, displayMode: true });
          return; // success
        } catch (_) { /* try next */ }
      }
      // Final fallback: clean plain math (looks like math, not LaTeX source)
      host.innerHTML = `<span class="math-render-plain">${escapeHtml(v7_plainMathFallback(attempts[0]))}</span>`;
    };

    wrap.querySelectorAll(".math-eq-render").forEach(host => {
      const latex = host.dataset.eqLatex || "";
      renderEq(host, latex);
    });

    // Reveal a single equation card: writes the equation slowly, then the
    // explanation cards + symbols appear in quick succession right after.
    const revealMathCard = (card) => {
      if (!card || card.dataset.revealed === "1") return;
      card.dataset.revealed = "1";
      const render = card.querySelector(".math-eq-render");
      const pen = card.querySelector(".math-eq-pen");
      if (pen) pen.classList.add("is-writing");
      if (render) setTimeout(() => render.classList.add("is-drawn"), 350);
      if (pen) setTimeout(() => pen.classList.remove("is-writing"), 5000);
      // Equation writes slowly (~4.6s); explanation cards + symbols appear
      // quickly right after the writing finishes (starting at 4800ms).
      const AFTER_WRITE = 4800;
      const metas = card.querySelectorAll("[data-meta]");
      metas.forEach((m, i) => setTimeout(() => m.classList.add("is-visible"), AFTER_WRITE + i * 160));
      const symbols = card.querySelector("[data-symbols]");
      if (symbols) setTimeout(() => symbols.classList.add("is-visible"), AFTER_WRITE + metas.length * 160 + 160);
      if (Number(card.dataset.eqIndex) === equations.length - 1) {
        setTimeout(() => v7_revealCta("ctaToChat"), AFTER_WRITE + metas.length * 160 + 700);
      }
    };

    // IntersectionObserver: equations 2+ only start writing once scrolled into
    // the centre band — so each waits for you to reach it.
    if (v7.streamObserver) v7.streamObserver.disconnect();
    v7.streamObserver = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) revealMathCard(e.target);
      });
    }, {
      rootMargin: "-30% 0px -30% 0px",
      threshold: 0.01,
    });
    const cards = [...wrap.querySelectorAll(".math-eq-card")];
    cards.forEach(c => v7.streamObserver.observe(c));
    // The first equation writes immediately on arrival (its centre starts below
    // the trigger band, so it wouldn't fire on its own).
    if (cards[0]) setTimeout(() => revealMathCard(cards[0]), 400);
  }

  /* ── ChatGPT-style chat (Phase 3.5) ── */
  function v7_renderChatBare(paper, peel) {
    const grid = document.getElementById("suggestionGrid");
    if (grid) {
      const questions = (peel.suggested_questions || []).slice(0, 4);
      grid.innerHTML = questions.map(q => `
        <button type="button" class="chat-bare-suggest" data-q="${escapeHtml(q)}">${escapeHtml(q)}</button>
      `).join("");
      grid.querySelectorAll(".chat-bare-suggest").forEach(btn => {
        btn.addEventListener("click", () => {
          const input = document.getElementById("chatInput");
          if (input) { input.value = btn.dataset.q; input.focus(); }
        });
      });
    }

    const log = document.getElementById("chatLog");
    if (log) {
      log.innerHTML = (state.currentMessages || []).map(m => v7_chatBubbleHtml(m.role, m.content)).join("");
      log.scrollTop = log.scrollHeight;
    }
  }

  function v7_chatBubbleHtml(role, content) {
    if (role === "user") {
      return `<div class="chat-msg-user">${escapeHtml(content)}</div>`;
    }
    const paragraphs = String(content || "").split(/\n\s*\n/).map(p => `<p>${escapeHtml(p)}</p>`).join("");
    return `
      <div class="chat-msg-assistant">
        <div class="chat-msg-assistant-avatar logo-avatar">${CHAT_LOGO_SVG}</div>
        <div class="chat-msg-assistant-body">${paragraphs}</div>
      </div>
    `;
  }

  /* ── Sidebar close button (Phase 4) ── */
  function v7_addSidebarCloseButton() {
    const sb = document.getElementById("sidebar");
    if (!sb) return;
    const head = sb.querySelector(".hs-head");
    if (!head || sb.querySelector(".sb-close-btn")) return;
    const btn = document.createElement("button");
    btn.className = "sb-close-btn";
    btn.type = "button";
    btn.setAttribute("aria-label", "Close sidebar");
    btn.title = "Close sidebar";
    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>`;
    head.appendChild(btn);
    btn.addEventListener("click", () => {
      sb.classList.add("closed");
      const mn = document.getElementById("main");
      if (mn) mn.classList.add("wide");
      const overlay = document.getElementById("mob-overlay");
      if (overlay) overlay.classList.remove("show");
    });
  }
  // Run once DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", v7_addSidebarCloseButton);
  } else {
    v7_addSidebarCloseButton();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
