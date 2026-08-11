/**
 * One placeholder string, used by all three pages.
 *
 * Each page reaches it differently — the table through `notReadyText`, the chart through
 * GraphMaker's `statusText.noPframe`, the run summary directly — so without a shared
 * constant the three drift into three slightly different sentences.
 */
export const NOT_READY_TEXT = 'Configure settings and click "Run" to see the data';
