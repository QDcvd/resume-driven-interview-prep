import { createRouter, createWebHistory } from "vue-router";
import Dashboard from "./views/Dashboard.vue";
import PreReview from "./views/PreReview.vue";
import Exam from "./views/Exam.vue";
import Review from "./views/Review.vue";
import Mistakes from "./views/Mistakes.vue";
import QuestionBank from "./views/QuestionBank.vue";
import KnowledgeCards from "./views/KnowledgeCards.vue";
import Candidates from "./views/Candidates.vue";
import Analytics from "./views/Analytics.vue";
import SettingsView from "./views/Settings.vue";
import Onboarding from "./views/Onboarding.vue";
import Interview from "./views/Interview.vue";
import InterviewHistory from "./views/InterviewHistory.vue";
export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: Dashboard },
    { path: "/onboarding", component: Onboarding },
    { path: "/interviews", component: InterviewHistory },
    { path: "/interview/:id", component: Interview },
    { path: "/attempts/:id/review", component: PreReview },
    { path: "/attempts/:id/exam", component: Exam },
    { path: "/attempts/:id/result", component: Review },
    { path: "/mistakes", component: Mistakes },
    { path: "/questions", component: QuestionBank },
    { path: "/knowledge", component: KnowledgeCards },
    { path: "/candidates", component: Candidates },
    { path: "/analytics", component: Analytics },
    { path: "/settings", component: SettingsView },
  ],
});
