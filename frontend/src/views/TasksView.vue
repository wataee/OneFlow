<template>
  <div class="tasks-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Задачи (Tasks)</h1>
        <p class="page-subtitle">Управление очередью асинхронных задач автоматизации</p>
      </div>
      <n-space>
        <n-button secondary :loading="loading" @click="fetchTasks">
          🔄 Обновить
        </n-button>
        <n-button type="primary" @click="showCreateModal = true">
          ➕ Создать задачу
        </n-button>
      </n-space>
    </div>

    <!-- Filter Bar -->
    <n-card size="small" class="filters-card">
      <n-space align="center">
        <span>Фильтры:</span>
        <n-select
          v-model:value="statusFilter"
          placeholder="Все статусы"
          clearable
          style="width: 180px"
          :options="statusOptions"
          @update:value="fetchTasks"
        />
        <n-select
          v-model:value="typeFilter"
          placeholder="Все типы задач"
          clearable
          style="width: 260px"
          :options="typeOptions"
          @update:value="fetchTasks"
        />
      </n-space>
    </n-card>

    <!-- Error Alert -->
    <n-alert v-if="error" type="error" style="margin-top: 16px" closable @close="error = ''">
      {{ error }}
    </n-alert>

    <!-- Table -->
    <n-card style="margin-top: 16px">
      <n-data-table
        :loading="loading"
        :columns="columns"
        :data="tasks"
        :pagination="pagination"
        :bordered="false"
      />
    </n-card>

    <!-- Create Task Modal -->
    <n-modal
      v-model:show="showCreateModal"
      preset="card"
      title="Создать новую задачу"
      style="width: 600px"
      :segmented="{ content: 'soft', footer: 'soft' }"
    >
      <n-form ref="formRef" :model="createModel">
        <n-form-item label="Тип задачи">
          <n-select v-model:value="createModel.type" :options="typeOptions" />
        </n-form-item>

        <n-form-item label="Входные данные (JSON)">
          <n-input
            v-model:value="createModel.inputDataRaw"
            type="textarea"
            :rows="6"
            placeholder='{"document_id": "KZ-100", "total": 150000}'
          />
        </n-form-item>

        <n-checkbox v-model:checked="createModel.forceReview">
          Спровоцировать Human Review (установить confidence &lt; threshold)
        </n-checkbox>
      </n-form>

      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreateModal = false">Отмена</n-button>
          <n-button type="primary" :loading="creating" @click="handleCreateTask">
            Отправить в очередь (202 Accepted)
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, h } from 'vue';
import { useRouter } from 'vue-router';
import {
  NCard,
  NSpace,
  NButton,
  NSelect,
  NAlert,
  NDataTable,
  NModal,
  NForm,
  NFormItem,
  NInput,
  NCheckbox,
  NTag,
  DataTableColumns,
} from 'naive-ui';
import { apiClient } from '@/api/client';
import StatusBadge from '@/components/StatusBadge.vue';
import type { Task, PaginatedResponse, TaskStatus, TaskType } from '@/types';

const router = useRouter();
const loading = ref(false);
const creating = ref(false);
const error = ref('');
const tasks = ref<Task[]>([]);
const totalCount = ref(0);

const statusFilter = ref<TaskStatus | null>(null);
const typeFilter = ref<TaskType | null>(null);

const showCreateModal = ref(false);
const createModel = reactive({
  type: 'DOCUMENT_PROCESSING' as TaskType,
  inputDataRaw: '{\n  "document_id": "INV-2026-99",\n  "declared_sum": 520000\n}',
  forceReview: false,
});

const statusOptions = [
  { label: 'В очереди (PENDING)', value: 'PENDING' },
  { label: 'В обработке (PROCESSING)', value: 'PROCESSING' },
  { label: 'На проверке (REVIEW)', value: 'REVIEW' },
  { label: 'Завершено (COMPLETED)', value: 'COMPLETED' },
  { label: 'Ошибка (FAILED)', value: 'FAILED' },
];

const typeOptions = [
  { label: 'DOCUMENT_PROCESSING', value: 'DOCUMENT_PROCESSING' },
  { label: 'NOMENCLATURE_MATCHING', value: 'NOMENCLATURE_MATCHING' },
  { label: 'BANK_OPERATION', value: 'BANK_OPERATION' },
  { label: 'WAREHOUSE_RECONCILIATION', value: 'WAREHOUSE_RECONCILIATION' },
];

const pagination = reactive({
  page: 1,
  pageSize: 20,
  itemCount: 0,
  showSizePicker: true,
  pageSizes: [10, 20, 50],
  onChange: (page: number) => {
    pagination.page = page;
    fetchTasks();
  },
  onUpdatePageSize: (pageSize: number) => {
    pagination.pageSize = pageSize;
    pagination.page = 1;
    fetchTasks();
  },
});

const columns: DataTableColumns<Task> = [
  {
    title: 'ID задачи',
    key: 'id',
    render(row) {
      return h(
        NButton,
        {
          text: true,
          type: 'primary',
          onClick: () => router.push(`/tasks/${row.id}`),
        },
        { default: () => row.id.slice(0, 8) + '...' }
      );
    },
  },
  {
    title: 'Тип',
    key: 'type',
    render(row) {
      return h(NTag, { size: 'small', bordered: false }, { default: () => row.type });
    },
  },
  {
    title: 'Статус',
    key: 'status',
    render(row) {
      return h(StatusBadge, { status: row.status });
    },
  },
  {
    title: 'Confidence',
    key: 'confidence',
    render(row) {
      if (row.confidence === null || row.confidence === undefined) return '-';
      const pct = Math.round(row.confidence * 100);
      return `${pct}%`;
    },
  },
  {
    title: 'Создана',
    key: 'created_at',
    render(row) {
      return new Date(row.created_at).toLocaleString('ru-RU');
    },
  },
  {
    title: 'Действия',
    key: 'actions',
    render(row) {
      return h(
        NButton,
        {
          size: 'small',
          secondary: true,
          onClick: () => router.push(`/tasks/${row.id}`),
        },
        { default: () => 'Подробнее' }
      );
    },
  },
];

const fetchTasks = async () => {
  loading.value = true;
  error.value = '';
  try {
    const params: Record<string, any> = {
      limit: pagination.pageSize,
      offset: (pagination.page - 1) * pagination.pageSize,
    };
    if (statusFilter.value) params.status = statusFilter.value;
    if (typeFilter.value) params.task_type = typeFilter.value;

    const resp = await apiClient.get<PaginatedResponse<Task>>('/tasks/', { params });
    tasks.value = resp.data.items;
    totalCount.value = resp.data.total;
    pagination.itemCount = resp.data.total;
  } catch (err: any) {
    error.value = err.message || 'Ошибка загрузки задач';
  } finally {
    loading.value = false;
  }
};

const handleCreateTask = async () => {
  let parsed = {};
  try {
    parsed = JSON.parse(createModel.inputDataRaw);
  } catch {
    alert('Неверный формат JSON во входных данных');
    return;
  }

  if (createModel.forceReview) {
    parsed = { ...parsed, force_review: true };
  }

  creating.value = true;
  try {
    await apiClient.post('/tasks/', {
      type: createModel.type,
      input_data: parsed,
    });
    showCreateModal.value = false;
    fetchTasks();
  } catch (err: any) {
    alert(err.message || 'Ошибка создания задачи');
  } finally {
    creating.value = false;
  }
};

onMounted(() => {
  fetchTasks();
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
  font-size: 24px;
  font-weight: 700;
}

.page-subtitle {
  margin: 4px 0 0 0;
  font-size: 13px;
  opacity: 0.7;
}

.filters-card {
  border-radius: 8px;
}
</style>
