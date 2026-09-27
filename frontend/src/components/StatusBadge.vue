<template>
  <n-tag :type="tagType" :bordered="false" round size="small">
    <template #icon>
      <span class="status-dot" :class="tagType" />
    </template>
    {{ labelText }}
  </n-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { NTag } from 'naive-ui';
import type { TaskStatus, ReviewStatus } from '@/types';

const props = defineProps<{
  status: TaskStatus | ReviewStatus | string;
}>();

const tagType = computed(() => {
  switch (props.status) {
    case 'PENDING':
      return 'warning';
    case 'PROCESSING':
      return 'info';
    case 'REVIEW':
      return 'warning';
    case 'COMPLETED':
    case 'RESOLVED':
      return 'success';
    case 'FAILED':
      return 'error';
    default:
      return 'default';
  }
});

const labelText = computed(() => {
  switch (props.status) {
    case 'PENDING':
      return 'В очереди';
    case 'PROCESSING':
      return 'В обработке';
    case 'REVIEW':
      return 'На проверке';
    case 'COMPLETED':
      return 'Завершено';
    case 'RESOLVED':
      return 'Решено';
    case 'FAILED':
      return 'Ошибка';
    default:
      return props.status;
  }
});
</script>

<style scoped>
.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 4px;
}
.status-dot.success { background-color: #18a058; }
.status-dot.warning { background-color: #f0a020; }
.status-dot.info { background-color: #2080f0; }
.status-dot.error { background-color: #d03050; }
.status-dot.default { background-color: #909399; }
</style>
