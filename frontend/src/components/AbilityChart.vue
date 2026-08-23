<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts";
import type { Ability } from "../types";
const props = defineProps<{ data: Ability[] }>();
const element = ref<HTMLElement>();
let chart: echarts.ECharts | undefined;
let resizeObserver: ResizeObserver | undefined;
function draw() {
  if (!element.value || !props.data.length) return;
  chart ??= echarts.init(element.value);
  chart.resize();
  chart.setOption({
    radar: {
      indicator: props.data.map((x) => ({ name: x.name, max: 100 })),
      splitNumber: 4,
      axisName: { color: "#556474" },
    },
    series: [
      {
        type: "radar",
        data: [
          {
            value: props.data.map((x) => x.score),
            areaStyle: { color: "#397bad44" },
            lineStyle: { color: "#2868a9" },
          },
        ],
      },
    ],
  });
}
onMounted(() => {
  if (element.value) {
    resizeObserver = new ResizeObserver(() => {
      if (!props.data.length) return;
      if (chart) chart.resize();
      else draw();
    });
    resizeObserver.observe(element.value);
  }
  draw();
});
watch(() => props.data, draw, { deep: true, flush: "post" });
onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  chart?.dispose();
});
</script>
<template>
  <div
    v-show="data.length"
    ref="element"
    style="height: 330px; width: 100%"
  />
  <div v-if="!data.length" class="ability-empty">暂无已评分数据</div>
</template>
