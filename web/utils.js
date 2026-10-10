export function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) return "";
    if (typeof unsafe !== 'string') {
        unsafe = JSON.stringify(unsafe, null, 2);
    }
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

export function renderMarkdown(text) {
    let escaped = escapeHtml(text);

    // Extract fenced code blocks into placeholders before <br> conversion
    const codeBlocks = [];
    escaped = escaped.replace(/```([\s\S]*?)```/g, (_, code) => {
        codeBlocks.push('<pre><code>' + code + '</code></pre>');
        return `%%CODEBLOCK_${codeBlocks.length - 1}%%`;
    });

    // Apply inline formatting and newline conversion outside code blocks
    escaped = escaped
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');

    // Restore code blocks
    escaped = escaped.replace(/%%CODEBLOCK_(\d+)%%/g, (_, i) => codeBlocks[parseInt(i)]);

    return escaped;
}
