<template>
  <div class="task-detail-page">
    <div class="page-header">
      <n-space align="center">
        <n-button secondary @click="$router.push('/tasks')">← Назад к списку</n-button>
        <h1 class="page-title">Задача #{{ task?.id.slice(0, 8) }}</h1>
        <status-badge v-if="task" :status="task.status" />
      </n-space>

      <n-space>
        <n-button v-if="task?.status === 'FAILED'" type="warning" :loading="retrying" @click="handleRetry">
          🔄 Повторить (Retry)
        </n-button>
        <n-button
          v-if="task?.status === 'PENDING'"
          type="primary"
          secondary
          :loading="executingSync"
          @click="handleExecuteSync"
        >
          ⚡ Запустить обработку (Sync)
        </n-button>
      </n-space>
    </div>

    <n-spin :show="loading">
      <n-grid cols="1 m:3" responsive="screen" :x-gap="16" :y-gap="16">
        <!-- Main details -->
        <n-gi span="2">
          <n-card title="Данные задачи" size="small">
            <n-descriptions bordered :column="2">
              <n-descriptions-item label="Тип задачи">
                <n-tag size="small" :bordered="false">{{ task?.type }}</n-tag>
              </n-descriptions-item>
              <n-descriptions-item label="Организация">
                <code>{{ task?.organization_id }}</code>
              </n-descriptions-item>
              <n-descriptions-item label="Уверенность (Confidence)">
                <span v-if="task?.confidence !== null">
                  <strong>{{ Math.round((task?.confidence || 0) * 100) }}%</strong>
                  ({{ task?.confidence }})
                </span>
                <span v-else>Не оценивалась</span>
              </n-descriptions-item>
              <n-descriptions-item label="Попыток (Retries)">
                {{ task?.retry_count }}
              </n-descriptions-item>
              <n-descriptions-item label="Дата создания">
                {{ task?.created_at ? new Date(task.created_at).toLocaleString('ru-RU') : '-' }}
              </n-descriptions-item>
              <n-descriptions-item label="Последнее обновление">
                {{ task?.updated_at ? new Date(task.updated_at).toLocaleString('ru-RU') : '-' }}
              </n-descriptions-item>
            </n-descriptions>

            <div v-if="task?.error" style="margin-top: 16px">
              <n-alert type="error" title="Ошибка выполнения">
                {{ task.error }}
              </n-alert>
            </div>

            <div style="margin-top: 16px">
              <h4>Входные данные (Input Data):</h4>
              <pre class="json-box">{{ JSON.stringify(task?.input_data, null, 2) }}</pre>
            </div>

            <div style="margin-top: 16px">
              <h4>Результат обработки (Output Data):</h4>
              <pre class="json-box" :class="{ empty: !task?.output_data }">{{
                task?.output_data ? JSON.stringify(task.output_data, null, 2) : 'Результат пока отсутствует (задача в обработке или ожидает проверки)'
              }}</pre>
            </div>
          </n-card>
        </n-gi>

        <!-- Sidebar: Files and Quick Links -->
        <n-gi>
          <n-card title="Прикрепленные файлы" size="small">
            <div v-if="files.length === 0" class="empty-hint">
              К этой задаче ещё не прикреплены файлы.
            </div>
            <n-list v-else hoverable clickable>
              <n-list-item v-for="file in files" :key="file.id">
                <div class="file-item">
                  <div class="file-info">
                    <span class="file-name">{{ file.filename }}</span>
                    <span class="file-size">{{ (file.size_bytes / 1024).toFixed(1) }} KB</span>
                  </div>
                  <n-button size="tiny" secondary @click="downloadFile(file)">
                    Скачать
                  </n-button>
                </div>
              </n-list-item>
            </n-list>
          </n-card>

          <n-card title="Аудит изменений" size="small" style="margin-top: 16px">
            <n-timeline size="medium">
              <n-timeline-item
                v-for="log in auditLogs"
                :key="log.id"
                :title="log.action"
                :time="new Date(log.created_at).toLocaleTimeString('ru-RU')"
              />
            </n-timeline>
          </n-card>
        </n-gi>
      </n-grid>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import {
  NGrid,
  NGi,
  NCard,
  NSpace,
  NButton,
  NDescriptions,
  NDescriptionsItem,
  NTag,
  NAlert,
  NSpin,
  NList,
  NListItem,
  NTimeline,
  NTimelineItem,
} from 'naive-ui';
import { apiClient } from '@/api/client';
import StatusBadge from '@/components/StatusBadge.vue';
import type { Task, FileMetadata, PaginatedResponse } from '@/types';

const route = useRoute();
const taskId = route.params.id as string;

const loading = ref(false);
const retrying = ref(false);
const executingSync = ref(false);
const task = ref<Task | null>(null);
const files = ref<FileMetadata[]>([]);
const auditLogs = ref<any[]>([]);

const fetchTaskData = async () => {
  loading.value = true;
  try {
    const resp = await apiClient.get<Task>(`/tasks/${taskId}`);
    task.value = resp.data;

    // Fetch attached files
    const filesResp = await apiClient.get<PaginatedResponse<FileMetadata>>('/files/', {
      params: { task_id: taskId },
    });
    files.value = filesResp.data.items;

    // Fetch audit events
    const auditResp = await apiClient.get<PaginatedResponse<any>>('/audit/', {
      params: { entity_type: 'Task' },
    });
    auditLogs.value = auditResp.data.items.filter((a) => a.entity_id === taskId);
  } finally {
    loading.value = false;
  }
};

const handleRetry = async () => {
  retrying.value = true;
  try {
    const resp = await apiClient.post<Task>(`/tasks/${taskId}/retry`);
    task.value = resp.data;
  } catch (err: any) {
    alert(err.message || 'Ошибка перезапуска задачи');
  } finally {
    retrying.value = false;
  }
};

const handleExecuteSync = async () => {
  executingSync.value = true;
  try {
    const resp = await apiClient.post<Task>(`/tasks/${taskId}/execute-sync`);
    task.value = resp.data;
    fetchTaskData();
  } catch (err: any) {
    alert(err.message || 'Ошибка обработки');
  } finally {
    executingSync.value = false;
  }
};

const downloadFile = (file: FileMetadata) => {
  window.open(`/api/v1/files/${file.id}/download`, '_blank');
};

onMounted(() => {
  fetchTaskData();
});
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
}

.json-box {
  background: var(--n-color-embedded, #1f242c);
  padding: 12px;
  border-radius: 6px;
  font-size: 12px;
  font-family: monospace;
  overflow-x: auto;
  border: 1px solid var(--n-border-color, #30363d);
}

.json-box.empty {
  font-style: italic;
  opacity: 0.6;
}

.file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.file-info {
  display: flex;
  flex-direction: column;
}

.file-name {
  font-weight: 500;
  font-size: 13px;
}

.file-size {
  font-size: 11px;
  opacity: 0.6;
}

.empty-hint {
  font-size: 13px;
  opacity: 0.6;
  text-align: center;
  padding: 16px 0;
}
</style>
