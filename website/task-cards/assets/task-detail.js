(() => {
  const main = document.querySelector('.task-detail-main');
  if (!main) return;
  main.id = 'task-detail-content';
  document.body.insertAdjacentHTML('afterbegin', `
    <a class="task-skip" href="#task-detail-content">Skip to content</a>
    <header class="task-site-header">
      <a href="https://yangsen-hub-dot.github.io/AISLE/index.html" aria-label="AISLE home">
        <img src="../assets/brand/aisle-logo-white.svg" alt="AISLE logo" width="1226" height="222">
      </a>
      <nav aria-label="Main navigation">
        <a href="https://yangsen-hub-dot.github.io/AISLE/index.html">Home</a>
        <a href="https://yangsen-hub-dot.github.io/AISLE/leaderboard.html">Leaderboard</a>
        <a href="../tasks.html" aria-current="true">Tasks</a>
        <a href="https://yangsen-hub-dot.github.io/AISLE/contribute.html">Contribute</a>
        <a href="https://yangsen-hub-dot.github.io/AISLE/index.html#join">Join us</a>
      </nav>
    </header>`);
})();
