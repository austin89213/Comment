from django.urls import reverse
from rest_framework import status
from django.contrib import messages

from comment.conf import settings
from comment.models import Comment
from comment.tests.base import BaseCommentTest, BaseCommentFlagTest, BaseCommentViewTest
from comment.tests.test_utils import BaseAnonymousCommentTest, AnonymousUser, timezone, signing


class CommentViewTestCase(BaseCommentViewTest):
    def setUp(self):
        super().setUp()
        self.all_comments = Comment.objects.all().count()
        self.parent_comments = Comment.objects.all_parents().count()
        self.data = {
            'content': 'comment body',
            'app_name': 'post',
            'model_name': 'post',
            'parent_id': '',
            'model_id': self.post_1.id
        }

    def increase_count(self, parent=False):
        if parent:
            self.parent_comments += 1

        self.all_comments += 1

    def get_url(self):
        return reverse('comment:create')

    def comment_count_test(self):
        self.assertEqual(Comment.objects.all_parents().count(), self.parent_comments)
        self.assertEqual(Comment.objects.all().count(), self.all_comments)

    def test_create_parent_and_child_comment(self):
        self.assertEqual(self.all_comments, 0)
        self.assertEqual(self.parent_comments, 0)

        # parent comment
        response = self.client.post(self.get_url(), data=self.data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'comment/comments/base.html')
        parent_comment = Comment.objects.get(object_id=self.post_1.id, parent=None)
        self.assertEqual(response.context.get('comment').id, parent_comment.id)
        self.assertTrue(response.context.get('comment').is_parent)

        self.increase_count(parent=True)
        self.comment_count_test()

        # child comment
        data = self.data.copy()
        data['parent_id'] = parent_comment.id
        response = self.client.post(self.get_url(), data=data)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'comment/comments/child_comment.html')
        child_comment = Comment.objects.get(object_id=self.post_1.id, parent=parent_comment)
        self.assertEqual(response.context.get('comment').id, child_comment.id)
        self.assertFalse(response.context.get('comment').is_parent)

        self.increase_count()
        self.comment_count_test()

        # create child comment with wrong id of parent comment
        data['parent_id'] = 100
        response = self.client.post(self.get_url(), data=data)
        self.assertEqual(response.status_code, 200)
        # this is the latest comment
        child_comment = Comment.objects.filter(object_id=self.post_1.id).order_by('-posted').first()
        self.assertTrue(child_comment.is_parent)
        self.assertIsNone(child_comment.parent)

    def test_create_comment_non_ajax_request(self):
        response = self.client_non_ajax.post(self.get_url(), data=self.data)
        self.assertEqual(response.status_code, 400)

    def test_create_anonymous_comment(self):
        self.client.logout()
        settings.COMMENT_ALLOW_ANONYMOUS = True
        data = self.data.copy()
        data['email'] = 'a@a.com'
        response = self.client.post(self.get_url(), data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(response, 'comment/comments/base.html')
        response_messages = response.context['messages']
        for r in response_messages:
            self.assertEqual(r.level, messages.INFO)
            self.assertEqual(r.message, (
                'We have have sent a verification link to your email. The comment will be '
                'displayed after it is verified.'
                )
            )
        # no change in comment count
        self.comment_count_test()


class TestEditComment(BaseCommentViewTest):
    def get_url(self, pk):
        return reverse('comment:edit', args=[pk])

    def test_edit_comment(self):
        comment = self.create_comment(self.content_object_1)
        self.assertEqual(Comment.objects.all().count(), 1)
        data = {
            'content': 'parent comment was edited',
            'app_name': 'post',
            'model_name': 'post',
            'model_id': self.post_1.id
        }
        self.assertEqual(comment.content, 'comment 1')
        response = self.client.get(self.get_url(comment.id), data=data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed('comment/comments/update_comment.html')
        self.assertEqual(response.context['comment_form'].instance.id, comment.id)

        response = self.client.post(self.get_url(comment.id), data=data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed('comment/comments/comment_content.html')
        self.assertEqual(Comment.objects.all().first().content, data['content'])

        data['content'] = ''
        with self.assertRaises(ValueError) as error:
            self.client.post(self.get_url(comment.id), data=data)
        self.assertIsInstance(error.exception, ValueError)

    def test_cannot_edit_comment_by_different_user(self):
        comment = self.create_comment(self.content_object_1)
        self.client.force_login(self.user_2)
        data = {
            'content': 'parent comment was edited',
            'app_name': 'post',
            'model_name': 'post',
            'model_id': self.post_1.id
        }
        self.assertEqual(comment.content, 'comment 1')
        self.assertEqual(comment.user.username, self.user_1.username)
        response = self.client.get(self.get_url(comment.id), data=data)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.reason_phrase, 'Forbidden')

        response = self.client.post(self.get_url(comment.id), data=data)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.reason_phrase, 'Forbidden')


class TestDeleteComment(BaseCommentViewTest):
    def get_url(self, pk):
        return reverse('comment:delete', args=[pk])

    def response_fails_test(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.reason_phrase, 'Forbidden')

    def test_delete_comment(self):
        comment = self.create_comment(self.content_object_1)
        init_count = Comment.objects.all().count()
        self.assertEqual(init_count, 1)
        response = self.client.get(self.get_url(comment.id), data=self.data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'comment/comments/comment_modal.html')
        self.assertContains(response, 'html_form')

        response = self.client.post(self.get_url(comment.id), data=self.data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'comment/comments/base.html')
        self.assertNotContains(response, 'html_form')
        self.assertRaises(Comment.DoesNotExist, Comment.objects.get, id=comment.id)
        self.assertEqual(Comment.objects.all().count(), init_count-1)

    def test_delete_comment_by_moderator(self):
        comment = self.create_comment(self.content_object_1)
        self.client.force_login(self.moderator)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.moderator.id)
        self.assertTrue(self.moderator.has_perm('comment.delete_flagged_comment'))
        self.assertEqual(comment.user, self.user_1)
        init_count = Comment.objects.count()
        self.assertEqual(init_count, 1)
        # moderator cannot delete un-flagged comment
        response = self.client.post(self.get_url(comment.id), data=self.data)
        self.assertEqual(response.status_code, 403)

        # moderator can delete flagged comment
        settings.COMMENT_FLAGS_ALLOWED = 1
        self.create_flag_instance(self.user_1, comment)
        self.create_flag_instance(self.user_2, comment)
        response = self.client.post(self.get_url(comment.id), data=self.data)
        self.assertEqual(response.status_code, 200)
        self.assertRaises(Comment.DoesNotExist, Comment.objects.get, id=comment.id)

    def test_delete_comment_by_admin(self):
        comment = self.create_comment(self.content_object_1)
        self.client.force_login(self.admin)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.admin.id)
        self.assertTrue(self.admin.groups.filter(name='comment_admin').exists())
        self.assertEqual(comment.user, self.user_1)
        init_count = Comment.objects.count()
        self.assertEqual(init_count, 1)

        # admin can delete any comment
        response = self.client.post(self.get_url(comment.id), data=self.data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Comment.objects.count(), init_count - 1)

    def test_cannot_delete_comment_by_different_user(self):
        comment = self.create_comment(self.content_object_1)
        self.client.force_login(self.user_2)
        self.assertEqual(comment.content, 'comment 1')
        self.assertEqual(comment.user.username, self.user_1.username)

        init_count = Comment.objects.all().count()
        self.assertEqual(init_count, 1)

        # test GET request
        response = self.client.get(self.get_url(comment.id), data=self.data)
        self.response_fails_test(response)

        # test POST request
        response = self.client.post(self.get_url(comment.id), data=self.data)
        self.response_fails_test(response)


class SetReactionViewTest(BaseCommentViewTest):
    def setUp(self):
        super().setUp()
        self.comment = self.create_comment(self.content_object_1)

    @staticmethod
    def get_url(obj_id, action):
        return reverse('comment:react', kwargs={
            'pk': obj_id,
            'reaction': action
        })

    def test_set_reaction_for_authenticated_users(self):
        """Test whether users can create/change reactions using view"""
        url = self.get_url(self.comment.id, 'like')
        response = self.client.post(url)
        data = {
            'status': 0,
            'likes': 1,
            'dislikes': 0,
            'msg': 'Your reaction has been updated successfully'
        }
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(response.json(), data)

    def test_set_reaction_for_old_comments(self):
        """Test backward compatibility for this update"""
        url = self.get_url(self.comment.id, 'like')
        # delete the reaction object
        self.comment.reaction.delete()
        response = self.client.post(url)
        data = {
            'status': 0,
            'likes': 1,
            'dislikes': 0,
            'msg': 'Your reaction has been updated successfully'
        }
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertDictEqual(response.json(), data)

    def test_set_reaction_for_unauthenticated_users(self):
        """Test whether unauthenticated users can create/change reactions using view"""
        url = self.get_url(self.comment.id, 'dislike')
        self.client.logout()
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, '{}?next={}'.format(settings.LOGIN_URL, url))

    def test_get_request(self):
        """Test whether GET requests are allowed or not"""
        url = self.get_url(self.comment.id, 'like')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_non_ajax_requests(self):
        """Test response if non AJAX requests are sent"""
        url = self.get_url(self.comment.id, 'like')
        response = self.client_non_ajax.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_incorrect_comment_id(self):
        """Test response when an incorrect comment id is passed"""
        url = self.get_url(102_876, 'like')
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_incorrect_reaction(self):
        """Test response when incorrect reaction is passed"""
        url = self.get_url(self.comment.id, 'likes')
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # test incorrect type
        url = self.get_url(self.comment.id, 1)
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SetFlagViewTest(BaseCommentFlagTest):
    def setUp(self):
        super().setUp()
        self.flag_data.update({
            'info': ''
            })
        self.response_data = {
            'status': 1
        }

    def get_url(self, obj_id=None):
        """
        A utility function to construct url.

        Args:
            obj_id (int): comment id, defaults to comment id of comment of the object.

        Returns:
            str
        """
        if not obj_id:
            obj_id = self.comment.id
        return reverse('comment:flag', kwargs={'pk': obj_id})

    def test_set_flag_for_flagging(self):
        url = self.get_url()
        data = self.flag_data
        response = self.client.post(url, data=data)
        response_data = {
            'status': 0,
            'flag': 1,
            'msg': 'Comment flagged'
        }
        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(response.json(), response_data)

    def test_set_flag_when_flagging_not_enabled(self):
        settings.COMMENT_FLAGS_ALLOWED = 0
        url = self.get_url()
        data = self.flag_data
        response = self.client.post(url, data=data)
        self.assertEqual(response.status_code, 403)
        settings.COMMENT_FLAGS_ALLOWED = 1

    def test_set_flag_for_flagging_old_comments(self):
        """Test backward compatibility for this update"""
        url = self.get_url()
        data = self.flag_data
        # delete the flag object
        self.comment.flag.delete()
        response = self.client.post(url, data=data)
        response_data = {
            'status': 0,
            'flag': 1,
            'msg': 'Comment flagged'
        }
        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(response.json(), response_data)

    def test_set_flag_for_unflagging(self):
        # un-flag => no reason is passed and the comment must be already flagged by the user
        url = self.get_url(self.comment_2.id)
        data = {}
        self.client.force_login(self.user_2)
        response = self.client.post(url, data=data)
        response_data = {
            'status': 0,
            'msg': 'Comment flag removed'
        }
        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(response.json(), response_data)

    def test_set_flag_for_unauthenticated_user(self):
        """Test whether unauthenticated user can create/delete flag using view"""
        url = self.get_url()
        self.client.logout()
        response = self.client.post(url, data=self.flag_data)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, '{}?next={}'.format(settings.LOGIN_URL, url))

    def test_get_request(self):
        """Test whether GET requests are allowed or not"""
        url = self.get_url()
        response = self.client.get(url, data=self.flag_data)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_non_ajax_requests(self):
        """Test response if non AJAX requests are sent"""
        url = self.get_url()
        response = self.client_non_ajax.post(url, data=self.flag_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_incorrect_comment_id(self):
        """Test response when an incorrect comment id is passed"""
        url = self.get_url(102_876)
        response = self.client.post(url, data=self.flag_data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_incorrect_reason(self):
        """Test response when incorrect reason is passed"""
        url = self.get_url()
        data = self.flag_data
        reason = -1
        data.update({'reason': reason})
        response = self.client.post(url, data=data)
        self.assertEqual(response.status_code, 200)


class ChangeFlagStateViewTest(BaseCommentFlagTest):
    def setUp(self):
        super().setUp()
        self.data = {
            'state': self.comment.flag.REJECTED
        }
        settings.COMMENT_FLAGS_ALLOWED = 1
        self.create_flag_instance(self.user_1, self.comment, **self.flag_data)
        self.create_flag_instance(self.user_2, self.comment, **self.flag_data)

    def get_url(self, comment=None):
        if not comment:
            comment = self.comment
        return reverse('comment:flag-change-state', kwargs={'pk': comment.id})

    def test_change_flag_state_for_unflagged_comment(self):
        settings.COMMENT_FLAGS_ALLOWED = 10
        self.comment.flag.toggle_flagged_state()
        self.assertFalse(self.comment.is_flagged)
        self.client.force_login(self.moderator)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.moderator.id)
        response = self.client.post(self.get_url(), data=self.data)
        self.assertEqual(response.status_code, 403)

    def test_change_flag_state_by_not_permitted_user(self):
        self.assertTrue(self.comment.is_flagged)
        self.client.force_login(self.user_1)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user_1.id)
        response = self.client.post(self.get_url(), data=self.data)
        self.assertEqual(response.status_code, 403)

    def test_change_flag_state_with_wrong_state_value(self):
        self.assertTrue(self.comment.is_flagged)
        self.client.force_login(self.moderator)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.moderator.id)
        self.assertEqual(self.comment.flag.state, self.comment.flag.FLAGGED)

        # valid state is REJECTED and RESOLVED
        self.data['state'] = self.comment.flag.UNFLAGGED
        response = self.client.post(self.get_url(), data=self.data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['state'], 0)
        self.assertEqual(self.comment.flag.state, self.comment.flag.FLAGGED)

    def test_change_flag_state_success(self):
        self.assertTrue(self.comment.is_flagged)
        self.client.force_login(self.moderator)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.moderator.id)
        self.assertEqual(self.comment.flag.state, self.comment.flag.FLAGGED)

        # valid state is REJECTED and RESOLVED
        self.data['state'] = self.comment.flag.REJECTED
        response = self.client.post(self.get_url(), data=self.data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['state'], self.comment.flag.REJECTED)
        self.comment.flag.refresh_from_db()
        self.assertEqual(self.comment.flag.moderator, self.moderator)
        self.assertEqual(self.comment.flag.state, self.comment.flag.REJECTED)


class ConfirmCommentViewTest(BaseAnonymousCommentTest, BaseCommentTest):
    def setUp(self):
        super().setUp()
        # although this will work for authenticated users as well.
        self.client.logout()
        self.request.user = AnonymousUser()
        self.init_count = Comment.objects.all().count()
        self.template_1 = 'comment/anonymous/discarded.html'
        self.template_2 = 'comment/comments/messages.html'
        self.template_3 = 'comment/bootstrap.html'

    def get_url(self, key=None):
        if not key:
            key = self.key
        return reverse('comment:confirm-comment', args=[key])

    def template_used_test(self, response):
        self.assertTemplateUsed(response, self.template_1)
        self.assertTemplateUsed(response, self.template_2)
        self.assertTemplateUsed(response, self.template_3)

    def test_bad_signature(self):
        key = self.key + 'invalid'
        response = self.client.get(self.get_url(key))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Comment.objects.all().count(), self.init_count)
        self.template_used_test(response)
        response_messages = response.context['messages']
        self.assertEqual(len(response_messages), 1)
        for r in response_messages:
            self.assertEqual(r.level, messages.ERROR)
            self.assertEqual(r.message, 'The link seems to be broken.')

    def test_comment_exists(self):
        comment_dict = self.comment_dict.copy()
        comment = self.create_anonymous_comment(posted=timezone.now(), email='a@a.com')
        init_count = self.init_count + 1
        comment_dict.update({
            'posted': str(comment.posted),
            'email': comment.email
        })
        key = signing.dumps(comment_dict)

        response = self.client.get(self.get_url(key))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Comment.objects.all().count(), init_count)
        self.template_used_test(response)
        response_messages = response.context['messages']
        self.assertEqual(len(response_messages), 1)
        for r in response_messages:
            self.assertEqual(r.level, messages.WARNING)
            self.assertEqual(r.message, 'The comment has already been verified.')

    def test_success(self):
        response = self.client.get(self.get_url())
        comment = Comment.objects.get(email=self.comment_obj.email, posted=self.time_posted)
        self.assertEqual(Comment.objects.all().count(), self.init_count + 1)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, comment.get_url(self.request))
