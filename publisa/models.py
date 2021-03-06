from django.db import models
from django.utils.translation import ugettext as _
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic
from django.utils.timesince import timeuntil, timesince
from django.db.models.signals import post_save
from django.db.models.query import QuerySet
from django.contrib.contenttypes.generic import GenericForeignKey
from django.db.models import F
from django.core.cache import cache
from django.utils.hashcompat import md5_constructor
from django.utils.http import urlquote

from publisa import settings as pub_settings

import datetime

STATUS_CHOICES = (
        (1, _('Draft')),
        (2, _('Finished')),
)

class PublishManager(models.Manager):
    """ Handle the publishing of items """
    def published(self):
        return self.get_query_set().filter(approved=True,
                                           publish__lte=datetime.datetime.now())

    def get_for_object(self, obj):
        """ Returns the published item for this object. """
        ctype = ContentType.objects.get_for_model(obj)
        try: p = self.get(content_type__pk=ctype.pk,
                          object_id=obj.pk)
        except Publish.DoesNotExist:
            return None
        else: return p

class PublishDescriptor(object):
    """
    A descriptor which returns all the published objects from the same model,
    or when an instance is given returns the Publish object.

    """
    def __get__(self, instance, model):
        if not instance:
            ctype = ContentType.objects.get_for_model(model)
            all_p = Publish.objects.published().filter(content_type__pk=ctype.pk)
            return model.objects.filter(pk__in=[p.object_id for p in all_p])
        else:
            return Publish.objects.get_for_object(instance)

class Publish(models.Model):
    """
    Publish model which can be inherited into any other model. This way you can
    manage if and when something should get published.

    """
    publish = models.DateTimeField(_('publish'),
                                   default=datetime.datetime.now,
                                   help_text=_('The date of release.'))
    approved = models.BooleanField(_('approve'),
                                   default=False)
    objects = PublishManager()
    banner = models.BooleanField(_('banner'),
                                 default=True,
                                 help_text=_('Should this item be published in the banner rotation?'))
    banner_image = models.ImageField(_('banner image'),
                                     upload_to='banners',
                                     blank=True,
                                     help_text=_('If left empty, the first photo in the article will be used.'))

    content_type = models.ForeignKey(ContentType, editable=False, verbose_name=_('content type'))
    object_id = models.PositiveIntegerField(editable=False)
    content_object = generic.GenericForeignKey('content_type', 'object_id')

    class Meta:
        ordering = ['-publish']
        verbose_name = _('published item')
        verbose_name_plural = _('published items')
        unique_together = ('content_type', 'object_id')

    def __unicode__(self):
        return '%(title)s' % {'title': self.content_object}

    def get_absolute_url(self):
        """
        The published item doesn't have it's own permalink. It just redirect
        to the permalink of the child model.

        """
        return self.content_object.get_absolute_url()

    def get_rss_title(self):
        if not hasattr(self.content_object, 'publish_rss_title'):
            return self.content_object
        return self.content_object.publish_rss_title

    def get_rss_description(self):
        if not hasattr(self.content_object, 'publish_rss_description'):
            return self.content_object
        return self.content_object.publish_rss_description

    def get_previous_published(self):
        """ Returns the previously published item or None if there's none. """
        prev_pub = self.get_previous_by_publish(approved=True)
        if prev_pub:
            return prev_pub.content_object
        else: return None

    def get_next_published(self):
        """ Returns the next published item or None if there's none. """
        next_pub = self.get_next_by_publish(approved=True)
        if next_pub:
            return next_pub.content_object
        else: return None

    def get_banner_image(self):
        """
        Returns an Django Image type containing the image for the banner.

        If the ``banner_image`` is empty, it will search for a ``publish_banner_image``
        inside the published item model. This method should return a Django Image.

        """
        if not self.content_object.allow_banners:
            return None
        else:
            if self.banner_image: return self.banner_image
            else:
                if hasattr(self.content_object, 'publish_banner_image'):
                    return self.content_object.publish_banner_image
                else: return None

    def published_humanised(self):
        """ Show humanised string of the publication date """
        if self.approved:
            now = datetime.datetime.now()
            if now > self.publish:
                return _('%s ago..') % timesince(self.publish)
            else:
                return _('%s left..') % timeuntil(self.publish)
        else:
            return _('Still needs approval..')
    published_humanised.short_description = _('Publication')
    published_humanised.allow_tags = True

class Status(models.Model):
    """
    A simple MetaClass which enables the content creator to mark his input as
    draft.

    """
    status = models.IntegerField(_('status'),
                                 choices=STATUS_CHOICES,
                                 default=1,
                                 help_text=_('Draft will not be published.'))

    class Meta:
        abstract = True

def post_save_published_at(sender, instance, created, **kwargs):
    """ If the published item has a ``published_at`` field, update it """
    if instance.approved and hasattr(instance.content_object, 'published_at'):
        instance.content_object.published_at = instance.publish
        instance.content_object.save()

def post_save_cache_clear(sender, instance, created, **kwargs):
    """
    If needed clear some of the cache keys so that the frontpage is updated.
    The keys can be set in the ``PUBLISA_CACHE_CLEAR_KEYS`` setting.

    """
    # clear normal cache
    cache.delete_many(list(pub_settings.PUBLISA_CACHE_CLEAR_KEYS))

    # clear template cache
    for k,v in pub_settings.PUBLISA_CACHE_CLEAR_TEMPLATE_KEYS.items():
        args = md5_constructor(u':'.join([urlquote(var) for var in v]))
        cache_key = 'template.cache.%s.%s' % (k, args.hexdigest())
        cache.delete(cache_key)

post_save.connect(post_save_cache_clear, sender=Publish)
post_save.connect(post_save_published_at, sender=Publish)
