/* tasks.js — TASKS page: orchestrate bar + kanban */

/* -- 8. Tasks page ------------------------------------------------------------- */

$('orchestrate-btn').addEventListener('click', () => {
  const goal = $('orchestrate-goal').value.trim();
  if (!goal) return;
  withLoading($('orchestrate-btn'), async () => {
    $('orchestrate-goal').value = '';
    await postJson('/api/orchestrate', { goal });
    refreshTasks();
  });
});

$('quick-btn').addEventListener('click', () => {
  const text = $('quick-task').value.trim();
  if (!text) return;
  withLoading($('quick-btn'), async () => {
    $('quick-task').value = '';
    await postJson('/api/tasks', { text });
    refreshTasks();
  });
});

// Hide finished cards (done + failed) off the board to reduce clutter. This is
// client-side only (no DELETE endpoint) so the next refreshTasks() restores them.
$('clear-done-btn').addEventListener('click', () => {
  const gone = document.querySelectorAll('#col-done .kcard, #col-failed .kcard').length;
  if (!gone) return;
  if (!confirm(`Hide ${gone} done/failed cards? (they reappear on the next refresh)`)) return;
  document.querySelectorAll('#col-done .kcard, #col-failed .kcard').forEach((c) => c.remove());
});



/* -- tasks boot -- */
refreshTasks();
setInterval(refreshTasks, 5000);
