<template>
  <div class="review-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Проверка результатов (Human-in-the-Loop)</h1>
        <p class="page-subtitle">
          Задачи, требующие экспертного решения бухгалтера или оператора перед фиксацией
        </p>
      </div>
      <n-button secondary :loading="loading" @click="fetchReviews">
        🔄 Обновить
      </n-button>
    </div>

    <!-- Error state -->
    <n-alert v-if="error" type="error" style="margin-bottom: 16px" closable @close="error = ''">
      {{ error }}
    </n-alert>

    <!-- Empty state -->
    <n-card v-if="!loading && reviews.length === 0" class="empty-card">
      <div class="empty-content">
        <span class="empty-icon">🎉</span>
        <h3>Все задачи проверены!</h3>
        <p>На данный момент нет задач, требующих ручного вмешательства или проверки.</p>
        <n-button type="primary" secondary @click="$router.push('/tasks')">
          Посмотреть список всех задач
        </n-button>
      </div>
    </n-card>

    <!-- Reviews list -->
    <n-spin :show="loading">
      <n-space vertical size="large">
        <n-card
          v-for="review in reviews"
          :key="review.id"
          class="review-card"
          hoverable
        >
          <template #header>
            <div class="review-header">
              <div>
                <span class="task-ref">Задача #{{ review.task_id.slice(0, 8) }}</span>
                <span class="created-at">{{ new Date(review.created_at).toLocaleString('ru-RU') }}</span>
              </div>
              <status-badge :status="review.status" />
            </div>
          </template>

          <div class="review-body">
            <div class="ai-box">
              <h4>🤖 Предложенный результат модели (AI Result):</h4>
              <pre class="json-code">{{ JSON.stringify(review.ai_result, null, 2) }}</pre>
            </div>

            <div v-if="review.status === 'RESOLVED'" class="resolution-box">
              <h4>Решение:</h4>
              <n-tag :type="review.user_decision === 'approve' ? 'success' : review.user_decision === 'reject' ? 'error' : 'info'">
                {{ review.user_decision?.toUpperCase() }}
              </n-tag>
              <p v-if="review.rejection_reason">Причина: {{ review.rejection_reason }}</p>
              <div v-if="review.proposed_changes">
                <h4>Итоговое значение человека:</h4>
                <pre class="json-code">{{ JSON.stringify(review.proposed_changes, null, 2) }}</pre>
              </div>
            </div>
          </div>

          <template v-if="review.status === 'PENDING'" #action>
            <n-space justify="end">
              <n-button type="error" secondary @click="openRejectModal(review)">
                ❌ Отклонить (Reject)
              </n-button>
              <n-button type="info" secondary @click="openEditModal(review)">
                ✏️ Исправить (Edit & Diff)
              </n-button>
              <n-button type="success" :loading="submittingId === review.id" @click="handleApprove(review)">
                ✅ Одобрить (Approve)
              </n-button>
            </n-space>
          </template>
        </n-card>
      </n-space>
    </n-spin>

    <!-- Reject Reason Modal -->
    <n-modal
      v-model:show="showRejectModal"
      preset="card"
      title="Отклонение результата AI"
      style="width: 500px"
    >
      <p>Укажите причину отклонения для сохранения в журнале аудита:</p>
      <n-input
        v-model:value="rejectReason"
        type="textarea"
        :rows="3"
        placeholder="Неверно определен контрагент или код назначения..."
      />
      <template #footer>
        <n-space justify="end">
          <n-button @click="showRejectModal = false">Отмена</n-button>
          <n-button type="error" :loading="submittingDecision" @click="submitReject">
            Подтвердить отклонение
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- Edit Modal -->
    <n-modal
      v-model:show="showEditModal"
      preset="card"
      title="Внесение правок человека (Human Correction)"
      style="width: 600px"
    >
      <p>Отредактируйте итоговый JSON. Система автоматически зафиксирует diff для дообучения моделей:</p>
      <n-input
        v-model:value="editJsonRaw"
        type="textarea"
        :rows="8"
        font-family="monospace"
      />
      <template #footer>
        <n-space justify="end">
          <n-button @click="showEditModal = false">Отмена</n-button>
          <n-button type="primary" :loading="submittingDecision" @click="submitEdit">
            Сохранить правку и завершить
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import {
  NCard,
  NSpace,
  NButton,
  NAlert,
  NSpin,
  NTag,
  NModal,
  NInput,
} from 'naive-ui';
import { apiClient } from '@/api/client';
import StatusBadge from '@/components/StatusBadge.vue';
import type { ReviewTask, PaginatedResponse } from '@/types';

const loading = ref(false);
const submittingId = ref<string | null>(null);
const submittingDecision = ref(false);
const error = ref('');
const reviews = ref<ReviewTask[]>([]);

const selectedReview = ref<ReviewTask | null>(null);
const showRejectModal = ref(false);
const rejectReason = ref('');

const showEditModal = ref(false);
const editJsonRaw = ref('');

const fetchReviews = async () => {
  loading.value = true;
  error.value = '';
  try {
    const resp = await apiClient.get<PaginatedResponse<ReviewTask>>('/reviews/');
    reviews.value = resp.data.items;
  } catch (err: any) {
    error.value = err.message || 'Ошибка загрузки задач на проверку';
  } finally {
    loading.value = false;
  }
};

const handleApprove = async (review: ReviewTask) => {
  submittingId.value = review.id;
  try {
    await apiClient.post(`/reviews/${review.id}/decision`, {
      decision: 'approve',
    });
    await fetchReviews();
  } catch (err: any) {
    alert(err.message || 'Ошибка одобрения');
  } finally {
    submittingId.value = null;
  }
};

const openRejectModal = (review: ReviewTask) => {
  selectedReview.value = review;
  rejectReason.value = '';
  showRejectModal.value = true;
};

const submitReject = async () => {
  if (!selectedReview.value) return;
  submittingDecision.value = true;
  try {
    await apiClient.post(`/reviews/${selectedReview.value.id}/decision`, {
      decision: 'reject',
      rejection_reason: rejectReason.value || 'Отклонено пользователем',
    });
    showRejectModal.value = false;
    await fetchReviews();
  } catch (err: any) {
    alert(err.message || 'Ошибка отклонения');
  } finally {
    submittingDecision.value = false;
  }
};

const openEditModal = (review: ReviewTask) => {
  selectedReview.value = review;
  editJsonRaw.value = JSON.stringify(review.ai_result, null, 2);
  showEditModal.value = true;
};

const submitEdit = async () => {
  if (!selectedReview.value) return;
  let parsed = {};
  try {
    parsed = JSON.parse(editJsonRaw.value);
  } catch {
    alert('Неверный синтаксис JSON');
    return;
  }

  submittingDecision.value = true;
  try {
    await apiClient.post(`/reviews/${selectedReview.value.id}/decision`, {
      decision: 'edit',
      edited_value: parsed,
    });
    showEditModal.value = false;
    await fetchReviews();
  } catch (err: any) {
    alert(err.message || 'Ошибка сохранения правки');
  } finally {
    submittingDecision.value = false;
  }
};

onMounted(() => {
  fetchReviews();
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

.review-card {
  border-radius: 8px;
}

.review-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.task-ref {
  font-weight: 700;
  font-size: 15px;
  margin-right: 12px;
}

.created-at {
  font-size: 12px;
  opacity: 0.6;
}

.json-code {
  background: var(--n-color-embedded, #1f242c);
  padding: 12px;
  border-radius: 6px;
  font-size: 12px;
  font-family: monospace;
  overflow-x: auto;
  border: 1px solid var(--n-border-color, #30363d);
}

.empty-card {
  text-align: center;
  padding: 48px 0;
}

.empty-icon {
  font-size: 48px;
  display: block;
  margin-bottom: 12px;
}
</style>
