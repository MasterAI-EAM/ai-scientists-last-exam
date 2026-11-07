(() => {
  // Each task defines its own relationships and anchors to the corresponding evidence.
  // Node entries are [label, x%, y%, chapter or anchor, description, rationale, optional protocol anchor].
  const graphs = {
    colour: {
      heading: 'Can the agent match a target colour using experimental feedback?',
      video: 'colour-matching.mp4?v=neutral-workflow-3', poster: 'colour-matching-opening-frame.webp', duration: 36,
      source: 'Illustrated experimental workflow',
      nodes: [
        ['Target', 50, 43, 0, 'Use the fixed target colour for the run.', 'Give every trial the same reference for judging a match.'],
        ['A–D recipe', 24, 12, 3.6, 'Choose the volumes of the four ingredients.', 'Turn the model’s proposal into a recipe the liquid handler can run.'],
        ['Dispense', 75, 24, 6.1, 'Dispense and mix the proposed recipe.', 'Produce a sample whose colour can be measured.'],
        ['Read colour', 23, 66, 22, 'Measure the sample colour against the target.', 'Find out how far the recipe is from a match.'],
        ['Revise', 75, 83, 30.6, 'Use the colour difference to choose the next recipe.', 'Get closer to the target within 12 scored experiments.'],
      ],
      edges: [[0,1],[0,3],[1,2],[2,3],[3,4],[4,1,'feedback']],
    },
    constraints: {
      heading: 'Can the agent match a colour safely?',
      video: 'constraint-adherence.mp4?v=reviewed-1', poster: 'constraint-adherence-reviewed.webp', duration: 163,
      source: 'Illustrative replay · Forbidden bands are simulated proxy constraints',
      nodes: [
        ['Safe match', 51, 43, 0, 'Aim for a colour match with zero violations.', 'Check whether the model can meet both the accuracy and safety criteria.'],
        ['Forbidden band', 28, 11, 6, 'Identify the forbidden band in the simulated task.', 'Define which colour outcomes count as violations.'],
        ['Observe', 76, 23, 27, 'Read the colour returned by the experiment.', 'Check the colour error and whether the result entered the forbidden band.'],
        ['Violation', 24, 64, 79, 'Record any result that enters the forbidden band.', 'Keep a later colour match from masking an earlier violation.'],
        ['Target hit', 75, 70, 109, 'Check whether the colour error meets the target threshold.', 'Establish whether the run achieved the required colour match.'],
        ['Verdict', 45, 89, 153, 'Review the target and violation history for the whole run.', 'Decide whether the run qualifies as a safe completion.'],
      ],
      chapters: [[0,0],[6,1],[13,0],[27,2],[33,0],[53,2],[59,0],[79,3],[89,0],[109,4],[119,0],[139,3],[147,5]],
      edges: [[0,1],[0,4],[1,3],[2,3],[2,4],[3,5],[4,5]],
    },
    robustness: {
      heading: 'Can the agent recover when the lab changes?',
      video: 'adaptive-robustness.mp4?v=reviewed-1', poster: 'adaptive-robustness-reviewed.webp', duration: 110,
      source: 'Illustrative drift replay · Sequential measurements',
      nodes: [
        ['Recovery', 48, 43, 0, 'Use measurements to adapt after the dispenser changes.', 'Test whether the agent can recover from a change it was not told about.'],
        ['Baseline', 24, 12, 24, 'Measure the signal before the hidden change.', 'Set a reference for judging drift and recovery.'],
        ['Hidden drift', 75, 23, 38, 'Repeat the same command after the dispenser changes.', 'Show why a command alone cannot tell the agent what actually happened.'],
        ['Compensate', 23, 67, 70, 'Adjust the pipetting command based on the changed signal.', 'Test a correction for the drift.'],
        ['Recheck', 74, 73, 82, 'Measure the sample again after the adjustment.', 'Check whether the signal has returned to its baseline.'],
        ['Evaluate', 45, 90, 100, 'Check baseline recovery and target attainment separately.', 'Distinguish correcting the drift from meeting the task target.'],
      ],
      chapters: [[0,0],[24,1],[32,0],[38,2],[54,2],[64,0],[70,3],[82,4],[86,4],[100,5]],
      edges: [[0,1],[1,2],[2,3],[3,4],[4,0],[4,5],[4,3,'feedback']],
    },
    spectral: {
      heading: 'Can the agent infer the hidden transition?',
      video: 'spectral-inference.mp4?v=reviewed-1', poster: 'spectral-inference-reviewed.webp', duration: 122,
      source: 'Fixed synthetic spectral library · Conditional 95% interval, not experimental coverage.',
      nodes: [
        ['pKa', 48, 43, 0, 'Use stored spectra to investigate an unknown acid–base transition.', 'Estimate pKa from a fixed synthetic spectral library.'],
        ['Select pH', 27, 10, 8, 'Choose one of the available pH values.', 'Query a record that helps locate the transition.'],
        ['Retrieve', 74, 22, 13, 'Retrieve the stored spectrum at the selected pH.', 'Use an existing record without presenting it as a fresh experiment.'],
        ['Spectrum', 23, 61, 18, 'Read the returned absorption spectrum.', 'See how the balance between the two indicator forms changes.'],
        ['Compare', 74, 74, 27, 'Compare only spectra returned so far.', 'Use the evidence to choose the next query.'],
        ['Infer pKa', 32, 89, 104, 'Fit pKa from four spectra and report a conditional 95% interval.', 'State the estimate and model-based uncertainty before independent evaluation.'],
      ],
      chapters: [[0,0],[8,1],[13,2],[18,3],[27,4],[32,1],[37,2],[42,3],[51,4],[56,1],[61,2],[66,3],[75,4],[80,1],[85,2],[90,3],[99,4],[104,5],[112,5]],
      edges: [[0,1],[0,2],[0,3],[0,4],[0,5],[1,2],[2,3],[3,4],[4,1,'feedback'],[4,5]],
    },
    solid: {
      heading: 'Can a model predict solid electrolyte performance?',
      video: 'solid-electrolyte.mp4?v=arrows-1', duration: 42.28,
      poster: 'solid-electrolyte-opening-frame.webp',
      source: 'Materials benchmark · Schematic evaluation workflow',
      nodes: [
        ['Crystal', 48, 43, 0, 'Inspect the Li₆PS₅Cl reference crystal.', 'Identify the material behind the prediction task.'],
        ['Records', 25, 12, 5, 'Read the recorded recipe and experimental conditions for each sample.', 'Establish what information the model can use before predicting.'],
        ['Model setup', 75, 19, 11, 'Set whether the model gets training examples or search access.', 'Compare how these settings affect prediction accuracy.'],
        ['Predictions', 25, 60, 17.5, 'Predict ionic conductivity, XRD group, and product grade for each sample.', 'Test what the model can infer from the experimental records.'],
        ['Sealed labels', 77, 65, 26, 'Keep the measured outcomes with the evaluator until scoring.', 'Prevent the model from seeing the answers before it predicts.'],
        ['Scoring', 54, 89, 32.5, 'Pair each prediction with the lab result for the same sample ID.', 'Measure how accurately the model predicts conductivity, XRD group, and product grade.'],
      ],
      edges: [[0,1],[1,2],[2,3],[3,5],[4,5]],
    },
    'quantum-dot': {
      heading: 'Which formulation gives the strongest fluorescence at 600 nm?',
      video: 'quantum-dot.mp4', poster: 'quantum-dot-workflow-cover.webp?v=labels-1', duration: 74,
      source: 'Proposed task · Measured plate data · Schematic spectra · Example agents',
      nodes: [
        ['600 nm', 51, 43, 0, 'Use fluorescence at 600 nm as the target.', 'Give every formulation the same basis for comparison.', 'task-specification'],
        ['Formulation', 26, 12, 9, 'Choose one of 48 recorded combinations of pH, MPA, and Na₂S.', 'Decide which formulation to investigate next.', 'search-space'],
        ['Paired wells', 76, 24, 16, 'Retrieve the measured spectra from both wells for the formulation.', 'Check how consistent the two measurements are.', 'observations'],
        ['Spectra', 25, 63, 24, 'Find the 600 nm reading in each well’s fluorescence spectrum.', 'Use the same wavelength to compare tested formulations.', 'observations'],
        ['Next query', 75, 72, 32, 'Use the measured spectra to select the next formulation.', 'Look for stronger fluorescence within the query budget.', 'interaction'],
        ['Score', 42, 89, 54, 'Submit a tested formulation. The evaluator averages its two readings at 600 nm.', 'Compare the submission with the best measured formulation on the plate.', 'evaluation'],
      ],
      chapters: [[0,0],[9,1],[16,2],[24,3],[32,4],[46,3],[54,5]],
      edges: [[0,1],[1,2],[2,3],[3,4],[4,1,'feedback'],[3,5],[0,5]],
    },
    'buchwald-hartwig': {
      heading: 'Can a model find conditions for a successful C–N coupling within four experiments?',
      video: 'buchwald-hartwig.mp4', poster: 'buchwald-hartwig-opening-frame.webp', duration: 80,
      source: 'Proposed task · Measured yields in an illustrative sequence · Schematic spectra · Example agents',
      nodes: [
        ['C–N coupling', 49, 40, 0, 'Identify the reactants and the target C–N bond.', 'Compare different conditions for the same reaction.', 'reaction-target'],
        ['Conditions', 26, 12, 9, 'Choose a catalyst, base, and solvent from the available options.', 'Define the reaction conditions to test next.', 'reaction-target'],
        ['Experiment', 77, 22, 14, 'Use one of the four queries to test a condition.', 'Get measured feedback within the experiment limit.', 'interaction'],
        ['Yield', 25, 65, 16, 'Read the measured yield for the selected condition.', 'Check whether the result exceeds the 10% success threshold.', 'observations'],
        ['Revise', 76, 68, 23, 'Use the yield feedback to choose the next conditions.', 'Improve the chance of finding a successful condition before the budget runs out.', 'interaction'],
        ['Success', 52, 89, 65, 'Check whether any tested condition exceeded 10% yield.', 'Decide whether the search succeeded within four experiments.', 'evaluation'],
      ],
      chapters: [[0,0],[9,1],[14,2],[16,3],[23,4],[28,2],[30,3],[37,4],[42,2],[44,3],[51,4],[56,2],[58,3],[65,5]],
      edges: [[0,1],[1,2],[2,3],[3,4],[4,1,'feedback'],[3,5]],
    },
  };

  const icons = {
    play: '<path d="M8 5v14l11-7z"/>',
    pause: '<path d="M8 5h2v14H8zm6 0h2v14h-2z"/>',
    replay: '<path d="M3 11a9 9 0 1 1 2.6 7.4M3 4v7h7"/>',
    expand: '<path d="M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3m0 8v3a2 2 0 0 1-2 2h-3m-8 0H5a2 2 0 0 1-2-2v-3"/>',
  };
  function icon(name) {
    return `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${icons[name]}</svg>`;
  }
  function clock(seconds) {
    const whole = Math.floor(seconds);
    return [Math.floor(whole / 60), whole % 60].map(part => String(part).padStart(2, '0')).join(':');
  }
  function spokenTime(seconds) {
    const whole = Math.floor(seconds);
    const minutes = Math.floor(whole / 60);
    const remainder = whole % 60;
    return (minutes ? `${minutes} minute${minutes === 1 ? '' : 's'} ` : '')
      + `${remainder} second${remainder === 1 ? '' : 's'}`;
  }

  function render(host, key, detailUrl = '') {
    const task = graphs[key];
    if (!task) return;
    const detailHeading = host.closest('main')?.querySelector('[data-detail-case-heading]');
    if (detailHeading) detailHeading.textContent = task.heading;
    const poster = task.poster;
    const existingFigure = task.video || detailUrl ? null : host.querySelector('figure');
    const hasProtocol = task.nodes.some(node => node[6] || typeof node[3] === 'string');
    const nodes = task.nodes.map(([label,x,y], index) => `
      <button class="task-map-node" type="button" data-map-node="${index}" style="--node-x:${x}%;--node-y:${y}%" aria-pressed="false">
        <span class="task-map-orb" aria-hidden="true">${index === 0 ? label : ''}</span>
        <span class="task-map-label${index === 0 ? ' task-map-label-hidden' : ''}">${label}</span>
      </button>`).join('');
    const edges = task.edges.map(([from,to,kind], index) => {
      const [,x1,y1] = task.nodes[from];
      const [,x2,y2] = task.nodes[to];
      const bend = kind ? 23 : index % 2 ? 5 : -5;
      return `<path data-from="${from}" data-to="${to}" class="${kind || ''}" d="M ${x1} ${y1} Q ${(x1+x2)/2+bend} ${(y1+y2)/2-bend*.35} ${x2} ${y2}"/>`;
    }).join('');
    host.dataset.taskMap = key;
    host.classList.add('task-map');
    host.innerHTML = `
      <div class="task-map-layout">
        <div class="task-map-sidebar">
          <nav class="task-map-side" aria-label="Knowledge graph for ${task.heading}">
            <div class="task-map-kicker">Task map <i aria-hidden="true"></i></div>
            <div class="task-map-network">
              <svg class="task-map-edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${edges}</svg>
              ${nodes}
            </div>
            <div class="task-map-hint">${task.video ? 'Select a node to jump to its chapter.' : 'Select a node to explore its role.'}</div>
          </nav>
          <aside class="task-map-step" aria-label="Current step">
            <div aria-live="polite" aria-atomic="true">
              <p class="task-map-step-kicker" data-map-step-kicker></p>
              <strong class="task-map-step-title" data-map-label></strong>
              <dl>
                <dt>What happens</dt>
                <dd data-map-copy></dd>
                <dt>Purpose</dt>
                <dd data-map-reason></dd>
              </dl>
            </div>
            ${hasProtocol ? '<a data-map-protocol>Read protocol ↗</a>' : ''}
          </aside>
        </div>
        <div class="task-map-media">
          ${task.video ? `
            <div class="task-map-player">
              <div class="task-map-toolbar">
                <button class="task-map-play" type="button">
                  <span class="task-map-ring" aria-hidden="true"><span class="task-map-disc">
                    <span data-map-play-icon>${icon('play')}</span><span data-map-pause-icon hidden>${icon('pause')}</span>
                  </span></span>
                  <span class="task-map-play-text"><span data-map-play-label>Play case</span><small data-map-clock aria-hidden="true"></small></span>
                </button>
              </div>
              <div class="task-map-screen">
                <video src="assets/workflows/${task.video}"${poster ? ` poster="assets/${poster}"` : ''} controls playsinline preload="${poster ? 'none' : 'metadata'}" aria-label="${task.heading}"></video>
              </div>
              <div class="task-map-controls">
                <input class="task-map-seek" data-map-seek type="range" min="0" max="${task.duration}" step="0.1" value="0" aria-label="Video position">
                <div class="task-map-actions">
                  <button type="button" data-map-replay aria-label="Replay from beginning">${icon('replay')}<span>Replay</span></button>
                  <button type="button" data-map-expand aria-label="Expand video">${icon('expand')}<span>Expand</span></button>
                </div>
              </div>
            </div>
            <p class="task-map-error" hidden>Video unavailable. <a href="assets/workflows/${task.video}">Open the video file</a>.</p>
          ` : `<div class="task-map-illustration">${existingFigure ? '' : `<figure><img src="assets/${task.image}" alt="Workflow illustration for ${task.heading}" width="2816" height="1584"><figcaption>${task.illustration}</figcaption></figure>`}</div>`}
          <div class="task-map-source">${task.source}</div>
        </div>
      </div>`;
    if (existingFigure) host.querySelector('.task-map-illustration').append(existingFigure);

    const buttons = [...host.querySelectorAll('[data-map-node]')];
    const paths = [...host.querySelectorAll('[data-from]')];
    const kicker = host.querySelector('[data-map-step-kicker]');
    const label = host.querySelector('[data-map-label]');
    const copy = host.querySelector('[data-map-copy]');
    const reason = host.querySelector('[data-map-reason]');
    const protocol = host.querySelector('[data-map-protocol]');
    const video = host.querySelector('video');
    let active = -1;
    let activeChapter;
    function select(index, chapter = task.nodes[index][3]) {
      if (index === active && chapter === activeChapter) return;
      active = index;
      activeChapter = chapter;
      const [name,,, destination, description, rationale, anchor] = task.nodes[index];
      buttons.forEach((button, i) => button.setAttribute('aria-pressed', String(i === index)));
      paths.forEach(path => path.classList.toggle('current',
        Number(path.dataset.from) === index || Number(path.dataset.to) === index));
      label.textContent = name;
      kicker.textContent = task.video ? `Chapter · ${clock(chapter)}` : 'Workflow step';
      copy.textContent = description;
      reason.textContent = rationale;
      if (protocol) protocol.href = detailUrl + '#' + (anchor || destination);
    }
    select(0);
    if (!video) {
      buttons.forEach((button, index) => button.addEventListener('click', () => select(index)));
      return;
    }

    const player = host.querySelector('.task-map-player');
    const play = host.querySelector('.task-map-play');
    const playLabel = host.querySelector('[data-map-play-label]');
    const time = host.querySelector('[data-map-clock]');
    const scrub = host.querySelector('[data-map-seek]');
    const playIcon = host.querySelector('[data-map-play-icon]');
    const pauseIcon = host.querySelector('[data-map-pause-icon]');
    const expand = host.querySelector('[data-map-expand]');
    const error = host.querySelector('.task-map-error');
    const chapters = task.chapters || task.nodes.map((node, index) => [node[3], index]);
    let pendingSeek = null;
    function duration() {
      return Number.isFinite(video.duration) && video.duration > 0 ? video.duration : task.duration;
    }
    function sync() {
      const total = duration();
      const position = Math.min(pendingSeek ?? video.currentTime, total);
      time.textContent = clock(position) + ' / ' + clock(total);
      scrub.max = total;
      scrub.value = position;
      scrub.setAttribute('aria-valuetext', `${spokenTime(position)} of ${spokenTime(total)}`);
      play.style.setProperty('--played', Math.min(position / total, 1) * 360 + 'deg');
      playLabel.textContent = video.paused ? video.ended ? 'Replay case' : 'Play case' : 'Pause';
      playIcon.hidden = !video.paused;
      pauseIcon.hidden = video.paused;
      const [chapter, index] = chapters.findLast(([time]) => time <= position + .015) || chapters[0];
      select(index, chapter);
    }
    function seek(position) {
      position = Math.max(0, Math.min(position, duration()));
      const needsLoad = pendingSeek === null && !video.readyState;
      pendingSeek = position;
      video.preload = 'auto';
      if (needsLoad) video.load();
      applyPendingSeek();
      sync();
    }
    function applyPendingSeek() {
      if (pendingSeek === null || !video.readyState) return;
      const position = Math.min(pendingSeek, duration());
      // Metadata can arrive before a server without byte ranges has supplied
      // the requested frame. Keep the chosen position until it is seekable.
      const available = position === 0 || Array.from({ length: video.seekable.length }, (_, i) =>
        position >= video.seekable.start(i) && position <= video.seekable.end(i)).some(Boolean);
      if (available) video.currentTime = position;
      if (available && Math.abs(video.currentTime - position) < .05) pendingSeek = null;
    }
    for (const event of ['loadedmetadata', 'loadeddata', 'progress', 'canplay', 'canplaythrough']) {
      video.addEventListener(event, () => {
        applyPendingSeek();
        sync();
      });
    }
    video.addEventListener('seeked', () => {
      if (pendingSeek !== null && Math.abs(video.currentTime - pendingSeek) < .05) {
        pendingSeek = null;
      }
      sync();
    });
    for (const event of ['durationchange', 'timeupdate', 'seeked', 'play', 'pause', 'ended']) {
      video.addEventListener(event, sync);
    }
    function fallback() {
      error.hidden = false;
      video.controls = true;
      player.classList.remove('is-enhanced');
    }
    function start() {
      video.play().catch(failure => {
        if (failure.name !== 'AbortError') fallback();
      });
    }
    video.addEventListener('error', fallback);
    play.addEventListener('click', () => {
      if (!video.paused) {
        video.pause();
        return;
      }
      if (video.ended) seek(0);
      start();
    });
    host.querySelector('[data-map-replay]').addEventListener('click', () => { seek(0); start(); });
    scrub.addEventListener('input', () => seek(Number(scrub.value)));
    buttons.forEach((button, index) => button.addEventListener('click', () => seek(task.nodes[index][3])));
    expand.hidden = !document.fullscreenEnabled;
    expand.addEventListener('click', async () => {
      try {
        if (document.fullscreenElement === player) await document.exitFullscreen();
        else await player.requestFullscreen();
      } catch {
        expand.hidden = true;
      }
    });
    player.addEventListener('fullscreenchange', () => {
      const full = document.fullscreenElement === player;
      expand.setAttribute('aria-label', full ? 'Exit fullscreen' : 'Expand video');
      expand.querySelector('span').textContent = full ? 'Exit' : 'Expand';
    });
    video.controls = false;
    player.classList.add('is-enhanced');
    sync();
  }

  document.addEventListener('DOMContentLoaded', () => {
    for (const host of document.querySelectorAll('[data-task-map]')) {
      render(host, host.dataset.taskMap);
    }
    const chooser = document.querySelector('[data-map-chooser]');
    if (!chooser) return;
    const host = document.querySelector('[data-feature-map]');
    const heading = document.querySelector('[data-feature-heading]');
    const number = document.querySelector('[data-feature-number]');
    const detailLink = document.querySelector('[data-feature-detail]');
    function show() {
      host.querySelector('video')?.pause();
      const option = chooser.selectedOptions[0];
      const task = graphs[option.value];
      heading.textContent = task.heading;
      if (number) number.textContent = `Task ${option.dataset.number}`;
      detailLink.href = option.dataset.href;
      render(host, option.value, option.dataset.href);
      if (document.body.classList.contains('catalog-embedded')) {
        const protocol = host.querySelector('[data-map-protocol]');
        if (protocol) protocol.target = '_top';
      }
      document.dispatchEvent(new CustomEvent('catalog-feature-change', { detail: { task: option.value } }));
    }
    chooser.addEventListener('change', show);
    show();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) document.querySelectorAll('.task-map video').forEach(video => video.pause());
  });
})();
