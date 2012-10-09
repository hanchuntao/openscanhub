# -*- coding: utf-8 -*-


from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.views.generic.list_detail import object_detail
from django.contrib.auth.decorators import login_required

from kobo.django.views.generic import object_list
from kobo.hub.models import Task

from models import *
#from forms import *


def mock_config_list(request):

    args = {
        "queryset": MockConfig.objects.all(),
        "allow_empty": True,
        "paginate_by": 50,
        "template_name": "mock_config/list.html",
        "template_object_name": "mock_config",
        "extra_context": {
            "title": "List mock configs",
        }
    }

    return object_list(request, **args)

def errata_scan_list(request):

    args = {
        "queryset": Scan.objects.all(),
#        "queryset": Scan.objects.exclude(base__isnull=True).\
#            exclude(base__exact=''),
        "allow_empty": True,
        "paginate_by": 50,
        "template_name": "errata/list.html",
        "template_object_name": "scan_list",
        "extra_context": {
            "title": "List errata scans",
        }
    }

    return object_list(request, **args)