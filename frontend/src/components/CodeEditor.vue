<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap, lineNumbers } from "@codemirror/view";
import { defaultKeymap, indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
const props = defineProps<{ modelValue: string }>();
const emit = defineEmits<{ (e: "update:modelValue", value: string): void }>();
const host = ref<HTMLElement>();
let view: EditorView | undefined;
onMounted(() => {
  view = new EditorView({
    parent: host.value,
    state: EditorState.create({
      doc: props.modelValue,
      extensions: [
        lineNumbers(),
        python(),
        keymap.of([...defaultKeymap, indentWithTab]),
        EditorView.updateListener.of((update) => {
          if (update.docChanged)
            emit("update:modelValue", update.state.doc.toString());
        }),
        EditorView.theme({
          "&": { height: "340px", fontSize: "14px" },
          ".cm-scroller": {
            overflow: "auto",
            fontFamily: "JetBrains Mono,Consolas,monospace",
          },
        }),
      ],
    }),
  });
});
onBeforeUnmount(() => view?.destroy());
</script>
<template><div ref="host" class="code-editor" /></template>
