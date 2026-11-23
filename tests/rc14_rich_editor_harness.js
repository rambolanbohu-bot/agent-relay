"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const source = fs.readFileSync(path.join(__dirname, "..", "transport", "extension", "content.js"), "utf8");
const start = source.indexOf("  function setComposerValue(");
const end = source.indexOf("  function doHealth(", start);
if (start < 0 || end < 0 || end - start > 7000) throw Error("editor_function_boundary_drift");
const checks = [];
function check(name, yes) { checks.push({ name, pass: !!yes }); }
let mode = "ok", editCount = 0, selectionCount = 0, clickCount = 0, editedValue = null;
const editor = {
  tagName: "DIV", textContent: "", isContentEditable: true,
  getAttribute(n) { return n === "contenteditable" ? "true" : null; },
  focus() { throw Error("focus must never be invoked"); },
  dispatchEvent() { throw Error("native edit should not double dispatch synthetic input"); }
};
const documentStub = {
  createRange() { return { selectNodeContents(el) { check("range_targets_editor", el === editor); } }; },
  execCommand(name, _show, value) {
    editCount += 1;
    if (name !== "insertText" || mode !== "ok") return false;
    editor.textContent = value;
    editedValue = value;
    return true;
  }
};
const textareaProto = {};
Object.defineProperty(textareaProto, "value", { configurable: true,
  set(value) { this.value = value; } });
const windowStub = {
  HTMLTextAreaElement: { prototype: textareaProto },
  HTMLInputElement: { prototype: {} },
  getSelection() { return { removeAllRanges(){ selectionCount++; },
      addRange(){ selectionCount++; } }; }
};
const context = { document: documentStub, window: windowStub,
  Event: class Event { constructor(type) { this.type=type; } },
  normText: s => String(s || "").replace(/\s+/g," ").trim() };
vm.createContext(context);
vm.runInContext(source.slice(start,end) +
  "\nglobalThis.editorFns = {setComposerValue, composerHasText};",context);
const {setComposerValue, composerHasText} = context.editorFns;
function throwsCode(fn, code) {
  try { fn(); return false; }
  catch(e) { return String(e.message||e).includes(code); }
}
setComposerValue(editor, "RC14 sample\nsecond line");
check("native_contenteditable_inserted", editedValue === "RC14 sample\nsecond line");
check("native_contenteditable_text_accepted", composerHasText(editor, editedValue));
check("native_exec_command_once", editCount === 1);
check("editor_focus_never_invoked", editor.focused !== true);
check("editor_selection_replaced", selectionCount === 2);
check("zero_clicks_in_input_path", clickCount === 0);
mode="reject"; editor.textContent=""; editor.focused=false;
check("native_rejection_fails_closed", throwsCode(()=>setComposerValue(editor,"reject"),"rich_editor_native_insert_rejected"));
check("rejected_input_not_falsely_accepted", !composerHasText(editor,"reject"));
check("rejection_never_clicked", clickCount === 0);
const multiline = "round 1 prev participant: X\\nReply starting with R11";
editor.textContent = multiline.replace(/\\n/g,"");
editor.innerText = multiline.replace(/\\n/g,"\\n");
check("multiline_visible_text_is_accepted", composerHasText(editor,multiline));
editor.innerText = "WRONG content";
check("wrong_multiline_not_accepted", !composerHasText(editor,multiline));
delete editor.innerText;
editor.textContent = "";
mode="ok"; editor.isContentEditable=false;
editor.getAttribute=()=>null;
check("noneditable_target_rejected", throwsCode(()=>setComposerValue(editor,"x"),"rich_editor_not_editable"));
editor.isContentEditable=true;
editor.getAttribute=()=> "true";
const saved=documentStub.execCommand;
documentStub.execCommand=undefined;
check("native_editor_unavailable_fails_closed", throwsCode(()=>setComposerValue(editor,"x"),"rich_editor_native_input_unsupported"));
documentStub.execCommand=saved;
const textArea={tagName:"TEXTAREA",value:"",events:[],dispatchEvent(ev){this.events.push(ev.type)}};
setComposerValue(textArea,"textarea-path");
check("textarea_native_setter_unbroken", textArea.value==="textarea-path");
check("textarea_input_change_events", textArea.events.join(",")==="input,change");
const selectors=source.slice(source.indexOf("  var SEND_SELECTORS = IS_CHATGPT"),source.indexOf("  var STOP_SELECTORS = IS_CHATGPT"));
check("known_composer_send_testid_present",selectors.includes("composer-send-button"));
check("known_localized_send_label_present",selectors.includes("发送消息"));
check("no_unscoped_generic_role_click",!selectors.includes("[role='button']"));
const result={all_pass:checks.every(c=>c.pass),checks};
console.log(JSON.stringify(result));
process.exitCode=result.all_pass ? 0 : 1;
